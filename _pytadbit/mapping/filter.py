"""
17 nov. 2014


"""
from __future__ import print_function
from builtins   import next
import multiprocessing as mu

from pytadbit.mapping.restriction_enzymes import count_re_fragments


MASKED = {1 : {'name': 'self-circle'       , 'reads': 0},
          2 : {'name': 'dangling-end'      , 'reads': 0},
          3 : {'name': 'error'             , 'reads': 0},
          4 : {'name': 'extra dangling-end', 'reads': 0},
          5 : {'name': 'too close from RES', 'reads': 0},
          6 : {'name': 'too short'         , 'reads': 0},
          7 : {'name': 'too large'         , 'reads': 0},
          8 : {'name': 'over-represented'  , 'reads': 0},
          9 : {'name': 'duplicated'        , 'reads': 0},
          10: {'name': 'random breaks'     , 'reads': 0},
          11: {'name': 'trans-chromosomic' , 'reads': 0}}


def apply_filter(fnam, outfile, masked, filters=None, reverse=False,
                 verbose=True):
    """
    Create a new file with reads filtered

    :param fnam: input file path, where non-filtered read are stored
    :param outfile: output file path, where filtered read will be stored
    :param masked: dictionary given by the
       :func:`pytadbit.mapping.filter.filter_reads`
    :param None filters: list of numbers corresponding to the filters we want
       to apply (numbers correspond to the keys in the masked dictionary)
    :param False reverse: if set, the resulting outfile will only contain the
       reads filtered, not the valid pairs.
    :param False verbose:

    :returns: number of reads kept
    """
    filters = filters or list(masked.keys())
    filter_handlers = {}
    for k in filters:
        try:
            fh = open(masked[k]['fnam'])
            val = next(fh).strip()
            filter_handlers[k] = [val, fh]
        except StopIteration:
            pass

    out = open(outfile, 'w')
    fhandler = open(fnam)
    # get the header
    pos = 0
    while True:
        line = next(fhandler)
        if not line.startswith('#'):
            break
        pos += len(line)
        out.write(line)
    fhandler.seek(pos)

    current = set([v for v, _ in list(filter_handlers.values())])
    count = 0
    count_cis_close = 0
    count_cis_far = 0
    count_trans = 0
    if reverse:
        for line in fhandler:
            read, rest = line.split('\t', 1)
            if read in current:
                count += 1
                c1, p1, _, _, _, _, c2, p2, _ = rest.split('\t', 8)
                if c1 != c2:
                    count_trans += 1
                elif abs(int(p2) - int(p1)) < 10_000:
                    count_cis_close += 1
                else:
                    count_cis_far += 1
                out.write(line)
            else:
                continue
            # iterate over different filters to update current filters
            for k in list(filter_handlers.keys()):
                if read != filter_handlers[k][0]:
                    continue
                try: # get next line from filter file
                    filter_handlers[k][0] = next(filter_handlers[k][1]).strip()
                except StopIteration:
                    filter_handlers[k][1].close()
                    del filter_handlers[k]
            current = set([v for v, _ in list(filter_handlers.values())])
    else:
        for line in fhandler:
            read, rest = line.split('\t', 1)
            if read not in current:
                count += 1
                c1, p1, _, _, _, _, c2, p2, _ = rest.split('\t', 8)
                if c1 != c2:
                    count_trans += 1
                elif abs(int(p2) - int(p1)) < 10_000:
                    count_cis_close += 1
                else:
                    count_cis_far += 1
                out.write(line)
                continue
            # iterate over different filters to update current filters
            for k in list(filter_handlers.keys()):
                if read != filter_handlers[k][0]:
                    continue
                try: # get next line from filter file
                    filter_handlers[k][0] = next(filter_handlers[k][1]).strip()
                except StopIteration:
                    filter_handlers[k][1].close()
                    del filter_handlers[k]
            current = set([v for v, _ in list(filter_handlers.values())])
    if verbose:
        print('    saving to file {:,} {} reads.'.format(
            count, 'filtered' if reverse else 'valid'))
    out.close()
    fhandler.close()
    return count, count_cis_close, count_cis_far, count_trans


def filter_reads(fnam, output=None, max_molecule_length=500,
                 over_represented=0.005, max_frag_size=100000,
                 min_frag_size=100, re_proximity=5, verbose=True,
                 savedata=None, min_dist_to_re=750, strict_duplicates=False,
                 fast=True):
    """
    Filter mapped pair of reads in order to remove experimental artifacts (e.g.
    dangling-ends, self-circle, PCR artifacts...)

    Applied filters are:
       1- self-circle        : reads are coming from a single RE fragment and
          point to the outside (----<===---===>---)
       2- dangling-end       : reads are coming from a single RE fragment and
          point to the inside (----===>---<===---)
       3- error              : reads are coming from a single RE fragment and
          point in the same direction
       4- extra dangling-end : reads are coming from different RE fragment but
          are close enough (< max_molecule length) and point to the inside
       5- too close from RES : semi-dangling-end filter, start position of one
          of the read is too close (5 bp by default) from RE cutting site. This
          filter is skipped in case read is involved in multi-contact. This
          filter may be too conservative for 4bp cutter REs.
       6- too short          : remove reads coming from small restriction less
          than 100 bp (default) because they are comparable to the read length
       7- too large          : remove reads coming from large restriction
          fragments (default: 100 Kb, P < 10-5 to occur in a randomized genome)
          as they likely represent poorly assembled or repeated regions
       8- over-represented   : reads coming from the top 0.5% most frequently
          detected restriction fragments, they may be prone to PCR artifacts or
          represent fragile regions of the genome or genome assembly errors
       9- duplicated         : the combination of the start positions of the
          reads is repeated -> PCR artifact (only keep one copy)
       10- random breaks     : start position of one of the read is too far (
          more than min_dist_to_re) from RE cutting site. Non-canonical
          enzyme activity or random physical breakage of the chromatin.

    :param fnam: path to file containing the pair of reads in tsv format, file
       generated by :func:`pytadbit.mapping.mapper.get_intersection`
    :param None output: PATH where to write files containing IDs of filtered
       reads. Uses fnam by default.
    :param 500 max_molecule_length: facing reads that are within
       max_molecule_length, will be classified as 'extra dangling-ends'
    :param 0.005 over_represented: to remove the very top fragment containing
       more reads
    :param 100000 max_frag_size: maximum fragment size allowed (fragments should
       not span over several bins)
    :param 100 min_frag_size: remove fragment that are too short (shorter than
       the sequenced read length)
    :param 5 re_proximity: should be adjusted according to RE site, to filter
       semi-dangling-ends
    :param 750 min_dist_to_re: minimum distance the start of a read should be
       from a RE site (usually 1.5 times the insert size). Applied in filter 10
    :param None savedata: PATH where to write the number of reads retained by
       each filter
    :param True fast: parallel version, requires 4 CPUs and more RAM memory
    :param False strict_duplicates: by default reads are considered duplicates if
       they coincide in genomic coordinates and strand; with strict_duplicates
       enabled, we also ask to consider read length (WARNING: this option is
       called strict, but it is more permissive).

    :return: dictionary with, as keys, the kind of filter applied, and as values
       a set of read IDs to be removed

    *Note: Filtering is not exclusive, one read can be filtered several times.*
    """

    if not output:
        output = fnam

    if strict_duplicates:
        _filter_duplicates = _filter_duplicates_strict
    else:
        _filter_duplicates = _filter_duplicates_loose

    if not fast: # mainly for debugging
        if verbose:
            print('filtering duplicates')
        sub_mask, total = _filter_duplicates(fnam, output)
        MASKED.update(sub_mask)
        if verbose:
            print('filtering same fragments')
        MASKED.update(_filter_same_frag(fnam, max_molecule_length, output))
        if verbose:
            print('filtering fro RE')
        MASKED.update(_filter_from_res(fnam, max_frag_size, min_dist_to_re,
                                       re_proximity, min_frag_size, output))
        if verbose:
            print('filtering over represented')
        MASKED.update(_filter_over_represented(fnam, over_represented, output))
    else:
        pool = mu.Pool(4)
        a = pool.apply_async(_filter_same_frag,
                             args=(fnam, max_molecule_length, output))
        b = pool.apply_async(_filter_from_res,
                             args=(fnam, max_frag_size, min_dist_to_re,
                                   re_proximity, min_frag_size, output))
        c = pool.apply_async(_filter_over_represented,
                             args=(fnam, over_represented, output))
        d = pool.apply_async(_filter_duplicates,
                             args=(fnam, output))
        pool.close()
        pool.join()
        sub_mask, total = d.get()
        MASKED.update(sub_mask)
        MASKED.update(b.get())
        MASKED.update(c.get())
        MASKED.update(a.get())

    # if savedata or verbose:
    #     bads = len(frozenset().union(*[masked[k]['reads'] for k in masked]))
    if savedata:
        out = open(savedata, 'w')
        out.write('Mapped both\t%d\n' % total)
        for k in range(1, len(MASKED) + 1):
            out.write('%s\t%d\n' % (MASKED[k]['name'], MASKED[k]['reads']))
        # out.write('Valid pairs\t%d\n' % (total - bads))
        out.close()
    if verbose:
        print('Filtered reads (and percentage of total):\n')
        print('     {:>25}  : {:12,} (100.00%)'.format('Mapped both', total))
        print('  ' + '-' * 53)
        for k in range(1, len(MASKED)):
            print('  {:2}- {:>25} : {:12,} ({:6.2f}%)'.format(
                k, MASKED[k]['name'], MASKED[k]['reads'],
                float(MASKED[k]['reads']) / total * 100))
    return MASKED


def _filter_same_frag(fnam, max_molecule_length, output):
    # t0 = time()
    masked = {1 : {'name': 'self-circle'       , 'reads': 0},
              2 : {'name': 'dangling-end'      , 'reads': 0},
              3 : {'name': 'error'             , 'reads': 0},
              4 : {'name': 'extra dangling-end', 'reads': 0}}
    outfil = {}
    for k in masked:
        masked[k]['fnam'] = output + '_' + masked[k]['name'].replace(' ', '_') + '.tsv'
        outfil[k] = open(masked[k]['fnam'], 'w')
    fhandler = open(fnam)
    line = next(fhandler)
    while line.startswith('#'):
        line = next(fhandler)
    try:
        while True:
            (read,
             cr1, pos1, sd1, _, _, re1,
             cr2, pos2, sd2, _, _, re2) = line.split('\t')
            ps1, ps2, sd1, sd2 = list(map(int, (pos1, pos2, sd1, sd2)))
            if cr1 == cr2:
                if re1 == re2.rstrip():
                    if sd1 != sd2:
                        if (ps2 > ps1) == sd2:
                            # ----<===---===>---                   self-circles
                            masked[1]["reads"] += 1
                            outfil[1].write(read + '\n')
                        else:
                            # ----===>---<===---                   dangling-ends
                            masked[2]["reads"] += 1
                            outfil[2].write(read + '\n')
                    else:
                        # --===>--===>-- or --<===--<===-- or same errors
                        masked[3]["reads"] += 1
                        outfil[3].write(read + '\n')
                elif (abs(ps1 - ps2) < max_molecule_length
                      and sd2 != sd1
                      and (ps2 > ps1) != sd2):
                    # different fragments but facing and very close
                    masked[4]["reads"] += 1
                    outfil[4].write(read + '\n')
            line = next(fhandler)
    except StopIteration:
        pass
    fhandler.close()
    # print 'done 1', time() - t0
    for k in masked:
        masked[k]['fnam'] = output + '_' + masked[k]['name'].replace(' ', '_') + '.tsv'
        outfil[k].close()
    return masked


def _filter_duplicates_strict(fnam, output):
    total = 0
    masked = {9 : {'name': 'duplicated'        , 'reads': 0}}
    outfil = {}
    for k in masked:
        masked[k]['fnam'] = output + '_' + masked[k]['name'].replace(' ', '_') + '.tsv'
        outfil[k] = open(masked[k]['fnam'], 'w')
    fhandler = open(fnam)
    line = next(fhandler)
    while line.startswith('#'):
        line = next(fhandler)
    (read,
     cr1, pos1, sd1, l1 , _, _,
     cr2, pos2, sd2, l2 , _, _) = line.split('\t')
    prev_elts = cr1, pos1, cr2, pos2, sd1, sd2, l1, l2
    for line in fhandler:
        (read,
         cr1, pos1, sd1, l1 , _, _,
         cr2, pos2, sd2, l2 , _, _) = line.split('\t')
        new_elts = cr1, pos1, cr2, pos2, sd1, sd2, l1, l2
        if prev_elts == new_elts:
            masked[9]["reads"] += 1
            outfil[9].write(read + '\n')
        total += 1
        prev_elts = new_elts
    fhandler.close()
    # print 'done 4', time() - t0
    for k in masked:
        masked[k]['fnam'] = output + '_' + masked[k]['name'].replace(' ', '_') + '.tsv'
        outfil[k].close()
    return masked, total


def _filter_duplicates_loose(fnam, output):
    total = 0
    masked = {9 : {'name': 'duplicated'        , 'reads': 0}}
    outfil = {}
    for k in masked:
        masked[k]['fnam'] = output + '_' + masked[k]['name'].replace(' ', '_') + '.tsv'
        outfil[k] = open(masked[k]['fnam'], 'w')
    fhandler = open(fnam)
    line = next(fhandler)
    while line.startswith('#'):
        line = next(fhandler)
    (read,
     cr1, pos1, sd1, _ , _, _,
     cr2, pos2, sd2, _ , _, _) = line.split('\t')
    prev_elts = cr1, pos1, cr2, pos2, sd1, sd2
    for line in fhandler:
        (read,
         cr1, pos1, sd1, _ , _, _,
         cr2, pos2, sd2, _ , _, _) = line.split('\t')
        new_elts = cr1, pos1, cr2, pos2, sd1, sd2
        if prev_elts == new_elts:
            masked[9]["reads"] += 1
            outfil[9].write(read + '\n')
        total += 1
        prev_elts = new_elts
    fhandler.close()
    # print 'done 4', time() - t0
    for k in masked:
        masked[k]['fnam'] = output + '_' + masked[k]['name'].replace(' ', '_') + '.tsv'
        outfil[k].close()
    return masked, total


def _filter_from_res(fnam, max_frag_size, min_dist_to_re,
                     re_proximity, min_frag_size, output):
    # t0 = time()
    masked = {5 : {'name': 'too close from RES', 'reads': 0},
              6 : {'name': 'too short'         , 'reads': 0},
              7 : {'name': 'too large'         , 'reads': 0},
              10: {'name': 'random breaks'     , 'reads': 0}}
    outfil = {}
    for k in masked:
        masked[k]['fnam'] = output + '_' + masked[k]['name'].replace(' ', '_') + '.tsv'
        outfil[k] = open(masked[k]['fnam'], 'w')
    fhandler = open(fnam)
    line = next(fhandler)
    while line.startswith('#'):
        line = next(fhandler)
    try:
        while True:
            (read,
             _, pos1, _, _, rs1, re1,
             _, pos2, _, _, rs2, re2) = line.split('\t')
            ps1, ps2, re1, rs1, re2, rs2 = list(map(int, (pos1, pos2, re1, rs1, re2, rs2)))
            diff11 = re1 - ps1
            diff12 = ps1 - rs1
            diff21 = re2 - ps2
            diff22 = ps2 - rs2
            if ((diff11 < re_proximity) or
                (diff12 < re_proximity) or
                (diff21 < re_proximity) or
                (diff22 < re_proximity)):
                # multicontacts excluded if fragment is internal (not the first)
                if not '~' in read:
                    masked[5]["reads"] += 1
                    outfil[5].write(read + '\n')
            # random breaks
            if (((diff11 > min_dist_to_re) and
                 (diff12 > min_dist_to_re)) or
                ((diff21 > min_dist_to_re) and
                 (diff22 > min_dist_to_re))):
                masked[10]["reads"] += 1
                outfil[10].write(read + '\n')
            dif1 = re1 - rs1
            dif2 = re2 - rs2
            if (dif1 < min_frag_size) or (dif2 < min_frag_size):
                masked[6]["reads"] += 1
                outfil[6].write(read + '\n')
            if (dif1 > max_frag_size) or (dif2 > max_frag_size):
                masked[7]["reads"] += 1
                outfil[7].write(read + '\n')
            line = next(fhandler)
    except StopIteration:
        pass
    fhandler.close()
    # print 'done 2', time() - t0
    for k in masked:
        masked[k]['fnam'] = output + '_' + masked[k]['name'].replace(' ', '_') + '.tsv'
        outfil[k].close()
    return masked


def _filter_over_represented(fnam, over_represented, output):
    # t0 = time()
    frag_count = count_re_fragments(fnam)
    num_frags = len(frag_count)
    cut = int((1 - over_represented) * num_frags + 0.5)
    # use cut-1 because it represents the length of the list
    cut = sorted([frag_count[crm] for crm in frag_count])[cut - 1]
    masked = {8 : {'name': 'over-represented'  , 'reads': 0}}
    outfil = {}
    for k in masked:
        masked[k]['fnam'] = output + '_' + masked[k]['name'].replace(' ', '_') + '.tsv'
        outfil[k] = open(masked[k]['fnam'], 'w')
    fhandler = open(fnam)
    line = next(fhandler)
    while line.startswith('#'):
        line = next(fhandler)
    try:
        while True:
            read, cr1,  _, _, _, rs1, _, cr2, _, _, _, rs2, _ = line.split('\t')
            if (frag_count.get((cr1, rs1), 0) > cut or
                  frag_count.get((cr2, rs2), 0) > cut):
                masked[8]["reads"] += 1
                outfil[8].write(read + '\n')
            line = next(fhandler)
    except StopIteration:
        pass
    fhandler.close()
    # print 'done 3', time() - t0
    for k in masked:
        masked[k]['fnam'] = output + '_' + masked[k]['name'].replace(' ', '_') + '.tsv'
        outfil[k].close()
    return masked


def _filter_yannick(fnam, maxlen, de_left, de_right, output):
    # t0 = time()
    masked = {11: {'name': 'Y Dangling L', 'reads': 0},
              12: {'name': 'Y Dangling R', 'reads': 0},
              13: {'name': 'Y Rejoined', 'reads': 0},
              14: {'name': 'Y Self Circle', 'reads': 0},
              15: {'name': 'Y Random Break', 'reads': 0},
              16: {'name': 'Y Contact Close', 'reads': 0},
              17: {'name': 'Y Contact Far', 'reads': 0},
              18: {'name': 'Y Contact Upstream', 'reads': 0},
              19: {'name': 'Y Contact Downstream', 'reads': 0},
              20: {'name': 'Y Other', 'reads': 0}}
    outfil = {}
    for k in masked:
        masked[k]['fnam'] = output + '_' + masked[k]['name'].replace(' ', '_') + '.tsv'
        outfil[k] = open(masked[k]['fnam'], 'w')
    fhandler = open(fnam)
    line = next(fhandler)
    while line.startswith('#'):
        line = next(fhandler)
    try:
        while True:
            (read,
             n1, pos1, strand1, _, rs1, re1,
             n2, pos2, strand2, _, rs2, re2) = line.split('\t')
            pos1, pos2, re1, rs1, re2, rs2, strand1, strand2 = list(map(int,
                    (pos1, pos2, re1, rs1, re2, rs2, strand1, strand2)))
            #lexicographic order for chromosomes
            if n1 > n2 or (n1 == n2 and pos2<pos1):
                pos1,pos2,n1,n2,re1,rs1,re2,rs2,strand1,strand2 = \
                   pos2,pos1,n2,n1,re2,rs2,re1,rs1,strand2,strand1
            closest1 = rs1 if (pos1-rs1 < re1-pos1) else re1
            closest2 = rs2 if (pos2-rs2 < re2-pos2) else re2
            cat=20 #fall-through is "Other"
            #contacts
            if n1 != n2 or (closest1 != closest2 and re1 != re2):
                if strand1==1 and re1-pos1 < maxlen and\
                        strand2==1 and re2-pos2 < maxlen:
                            cat=18
                elif strand1==1 and re1-pos1 < maxlen and\
                        strand2==0 and pos2-rs2 < maxlen and pos2-pos1>=maxlen:
                            cat=17
                elif strand1==0 and pos1-rs1 < maxlen and\
                        strand2==1 and re2-pos2 < maxlen:
                            cat=16
                elif strand1==0 and pos1-rs1 < maxlen and\
                        strand2==0 and pos2-rs2 < maxlen:
                            cat=19
            #self circles
            if re1 == re2 and strand1==0 and strand2==1 and pos1-rs1<maxlen\
                    and re2-pos2<maxlen:
                        cat=14
            #random, rejoined and dangling
            if n1==n2 and pos2-pos1<maxlen and strand1==1 and strand2==0:
                if re2==re1:
                    cat=15
                elif re1 <= rs2:
                    cat=13
                if pos1 - closest1 in de_left:
                    cat=11
                if pos2 - closest2 in de_right:
                    cat=12
            #apply classification
            masked[cat]["reads"] += 1
            outfil[cat].write(read + '\n')
            line = next(fhandler)
    except StopIteration:
        pass
    fhandler.close()
    for k in masked:
        masked[k]['fnam'] = output + '_' +\
                masked[k]['name'].replace(' ', '_') + '.tsv'
        outfil[k].close()
    return masked
