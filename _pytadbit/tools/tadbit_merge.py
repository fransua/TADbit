"""

information needed

 - path working directory with parsed reads

"""
from __future__ import print_function
from argparse                        import HelpFormatter
from os                              import path, remove, system
from string                          import ascii_letters
from random                          import random
from shutil                          import copyfile
from warnings                        import warn
from distutils.version               import LooseVersion
from multiprocessing                 import cpu_count
from subprocess                      import Popen, PIPE
import sqlite3 as lite
import time

from pytadbit                        import load_hic_data_from_bam
from pytadbit.mapping.analyze        import get_reproducibility
from pytadbit.mapping.analyze        import correlate_matrices
from pytadbit.mapping.analyze        import eig_correlate_matrices
from pytadbit.utils.sqlite_utils     import already_run, digest_parameters
from pytadbit.utils.sqlite_utils     import add_path, get_jobid, print_db
from pytadbit.utils.sqlite_utils     import get_path_id, retry
from pytadbit.utils.file_handling    import mkdir, which, magic_open
from pytadbit.mapping.filter         import MASKED
from pytadbit.utils                  import printime


DESC = ('load two working directories with different Hi-C data samples and ' +
        'merges them into a new working directory generating some statistics')

def run(opts):
    check_options(opts)

    samtools = which(opts.samtools)
    launch_time = time.localtime()

    param_hash = digest_parameters(opts)

    reso1 = reso2 = None
    if opts.bam1:
        mreads1 = path.realpath(opts.bam1)
        biases1 = opts.biases1
    else:
        biases1, mreads1, reso1 = load_parameters_fromdb(
            opts.workdir1, opts.jobid1, opts, opts.tmpdb1)
        mreads1 = path.join(opts.workdir1, mreads1)
        try:
            biases1 = path.join(opts.workdir1, biases1)
        except AttributeError:
            biases1 = None
        except TypeError:  # Py3
            biases1 = None

    if opts.bam2:
        mreads2 = path.realpath(opts.bam2)
        biases2 = opts.biases2
    else:
        biases2, mreads2, reso2 = load_parameters_fromdb(
            opts.workdir2, opts.jobid2, opts, opts.tmpdb2)
        mreads2 = path.join(opts.workdir2, mreads2)
        try:
            biases2 = path.join(opts.workdir2, biases2)
        except AttributeError:
            biases2 = None
        except TypeError:  # Py3
            biases1 = None

    filter_exclude = opts.filter

    if reso1 != reso2:
        raise Exception('ERROR: differing resolutions between experiments to '
                        'be merged')

    mkdir(path.join(opts.workdir, '00_merge'))

    if opts.skip_comparison[0] is not None:
        printime('  - loading first sample %s' % (mreads1))
        hic_data1 = load_hic_data_from_bam(mreads1, opts.reso, biases=biases1,
                                           tmpdir=path.join(opts.workdir, '00_merge'),
                                           ncpus=opts.cpus,
                                           filter_exclude=filter_exclude)

        printime('  - loading second sample %s' % (mreads2))
        hic_data2 = load_hic_data_from_bam(mreads2, opts.reso, biases=biases2,
                                           tmpdir=path.join(opts.workdir, '00_merge'),
                                           ncpus=opts.cpus,
                                           filter_exclude=filter_exclude)

        if opts.workdir1 and opts.workdir2:
            masked1 = {'valid-pairs': {'count': 0}}
            masked2 = {'valid-pairs': {'count': 0}}
        else:
            masked1 = {'valid-pairs': {'count': sum(hic_data1.values())}}
            masked2 = {'valid-pairs': {'count': sum(hic_data2.values())}}

        decay_corr_dat = path.join(opts.workdir, '00_merge', 'decay_corr_dat_%s_%s.txt' % (opts.reso, param_hash))
        decay_corr_fig = path.join(opts.workdir, '00_merge', 'decay_corr_dat_%s_%s.png' % (opts.reso, param_hash))
        eigen_corr_dat = path.join(opts.workdir, '00_merge', 'eigen_corr_dat_%s_%s.txt' % (opts.reso, param_hash))
        eigen_corr_fig = path.join(opts.workdir, '00_merge', 'eigen_corr_dat_%s_%s.png' % (opts.reso, param_hash))

        printime('  - comparing experiments')
        if 1 not in opts.skip_comparison:
            printime('    => correlation between equidistant loci')
            corr, _, scc, std, bads = correlate_matrices(
                hic_data1, hic_data2, normalized=opts.norm,
                remove_bad_columns=True, savefig=decay_corr_fig,
                savedata=decay_corr_dat, get_bads=True)
            print('         - correlation score (SCC): %.4f (+- %.7f)' % (scc, std))
        else:
            corr, scc, std = 0
            bads = {}
        if 2 not in opts.skip_comparison:
            printime('    => correlation between eigenvectors')
            eig_corr = eig_correlate_matrices(hic_data1, hic_data2, normalized=opts.norm,
                                            remove_bad_columns=True, nvect=6,
                                            savefig=eigen_corr_fig,
                                            savedata=eigen_corr_dat)
        else:
            eig_corr = 0
        if 3 not in opts.skip_comparison:
            printime('    => reproducibility score')
            reprod = get_reproducibility(hic_data1, hic_data2, num_evec=20, normalized=opts.norm,
                                        verbose=False, remove_bad_columns=True)
            print('         - reproducibility score: %.4f' % (reprod))
        else:
            reprod = 0
        ncols = len(hic_data1)
    else:
        ncols = 0
        decay_corr_dat = 'None'
        decay_corr_fig = 'None'
        eigen_corr_dat = 'None'
        eigen_corr_fig = 'None'
        masked1 = {}
        masked2 = {}

        corr = eig_corr = scc = std = reprod = 0
        bads = {}

    # merge inputs
    mkdir(path.join(opts.workdir, '03_filtered_reads'))
    outbam = path.join(opts.workdir, '03_filtered_reads',
                       'intersection_%s.bam' % (param_hash))

    if not opts.skip_merge:
        outbam = path.join(opts.workdir, '03_filtered_reads',
                           'intersection_%s.bam' % (param_hash))
        printime('  - Mergeing experiments')
        system(samtools  + ' merge -@ %d %s %s %s' % (opts.cpus, outbam, mreads1, mreads2))
        printime('  - Indexing new BAM file')
        # check samtools version number and modify command line
        version = LooseVersion([l.split()[1]
                                for l in Popen(samtools, stderr=PIPE,
                                               universal_newlines=True).communicate()[1].split('\n')
                                if 'Version' in l][0])
        if version > LooseVersion('1.3.1'):
            system(samtools  + ' index -@ %d %s' % (opts.cpus, outbam))
        else:
            system(samtools  + ' index %s' % (outbam))
    else:
        outbam = ''

    finish_time = time.localtime()
    save_to_db (opts, mreads1, mreads2, decay_corr_dat, decay_corr_fig,
                len(list(bads.keys())), ncols, scc, std, reprod,
                eigen_corr_dat, eigen_corr_fig, outbam, corr, eig_corr,
                biases1, biases2, masked1, masked2, launch_time, finish_time)
    printime('\nDone.')


@retry(lite.OperationalError, tries=20, delay=2)
def save_to_db(opts, mreads1, mreads2, decay_corr_dat, decay_corr_fig,
               nbad_columns, ncolumns, scc, std, reprod,
               eigen_corr_dat, eigen_corr_fig, outbed, corr, eig_corr,
               biases1, biases2, masked1, masked2, launch_time, finish_time):
    if 'tmpdb' in opts and opts.tmpdb:
        # check lock
        while path.exists(path.join(opts.workdir, '__lock_db')):
            time.sleep(0.5)
        # close lock
        open(path.join(opts.workdir, '__lock_db'), 'a').close()
        # tmp file
        dbfile = opts.tmpdb
        try: # to copy in case read1 was already mapped for example
            copyfile(path.join(opts.workdir, 'trace.db'), dbfile)
        except IOError:
            pass
    else:
        dbfile = path.join(opts.workdir, 'trace.db')
    con = lite.connect(dbfile)
    with con:
        cur = con.cursor()
        cur.execute("""SELECT name FROM sqlite_master WHERE
                       type='table' AND name='MERGE_OUTPUTs'""")
        if not cur.fetchall():
            cur.execute("""
            create table PATHs
               (Id integer primary key,
                JOBid int, Path text, Type text,
                unique (Path))""")
            cur.execute("""
            create table JOBs
               (Id integer primary key,
                Parameters text,
                Launch_time text,
                Finish_time text,
                Type text,
                Parameters_md5 text,
                unique (Parameters_md5))""")
            cur.execute("""
            create table FILTER_OUTPUTs
               (Id integer primary key,
                PATHid int,
                Name text,
                Count int,
                JOBid int,
                unique (PATHid))""")
            cur.execute("""
            create table MERGE_OUTPUTs
               (Id integer primary key,
                JOBid int,
                Wrkd1Path int,
                Wrkd2Path int,
                Bed1Path int,
                Bed2Path int,
                MergePath int,
                unique (JOBid))""")
            cur.execute("""
            create table MERGE_STATs
               (Id integer primary key,
                JOBid int,
                Inputs text,
                decay_corr text,
                eigen_corr text,
                reprod real,
                scc real,
                std_scc real,
                N_columns int,
                N_filtered int,
                Resolution int,
                bias1Path int,
                bias2Path int,
                unique (JOBid))""")
        try:
            parameters = digest_parameters(opts, get_md5=False)
            param_hash = digest_parameters(opts, get_md5=True )
            cur.execute("""
            insert into JOBs
            (Id  , Parameters, Launch_time, Finish_time, Type   , Parameters_md5)
            values
            (NULL,       '%s',        '%s',        '%s', 'Merge',           '%s')
            """ % (parameters,
                   time.strftime("%d/%m/%Y %H:%M:%S", launch_time),
                   time.strftime("%d/%m/%Y %H:%M:%S", finish_time), param_hash))
        except lite.IntegrityError:
            pass

        jobid = get_jobid(cur)
        add_path(cur, decay_corr_dat, 'CORR'      , jobid, opts.workdir)
        add_path(cur, decay_corr_fig, 'FIGURE'    , jobid, opts.workdir)
        add_path(cur, eigen_corr_dat, 'CORR'      , jobid, opts.workdir)
        add_path(cur, eigen_corr_fig, 'FIGURE'    , jobid, opts.workdir)

        add_path(cur, opts.workdir , 'WORKDIR'    , jobid)
        add_path(cur, opts.workdir1, 'WORKDIR1'   , jobid, opts.workdir)
        add_path(cur, opts.workdir2, 'WORKDIR2'   , jobid, opts.workdir)
        add_path(cur, mreads1      , 'EXT_HIC_BAM', jobid, opts.workdir)
        add_path(cur, mreads2      , 'EXT_HIC_BAM', jobid, opts.workdir)
        if not opts.skip_merge:
            add_path(cur, outbed   , 'HIC_BAM'    , jobid, opts.workdir)

        if opts.norm:
            add_path(cur, biases1      , 'BIASES'     , jobid, opts.workdir)
            add_path(cur, biases2      , 'BIASES'     , jobid, opts.workdir)

            biasid1 = get_path_id(cur, biases1, opts.workdir)
            biasid2 = get_path_id(cur, biases2, opts.workdir)
        else:
            biasid1 = 0
            biasid2 = 0

        cur.execute("select id from paths where path = '%s'" % (
            path.relpath(mreads1, opts.workdir)))
        bed1 = cur.fetchall()[0][0]
        if opts.workdir1:
            cur.execute("select id from paths where path = '%s'" % (
                path.relpath(opts.workdir1, opts.workdir)))
            w1path = cur.fetchall()[0][0]
        else:
            w1path = 0
        cur.execute("select id from paths where path = '%s'" % (
            path.relpath(mreads2, opts.workdir)))
        bed2 = cur.fetchall()[0][0]
        if opts.workdir2:
            cur.execute("select id from paths where path = '%s'" % (
                path.relpath(opts.workdir2, opts.workdir)))
            w2path = cur.fetchall()[0][0]
        else:
            w2path = 0
        if not opts.skip_merge:
            cur.execute("select id from paths where path = '%s'" % (
                path.relpath(outbed, opts.workdir)))
            outbedid = cur.fetchall()[0][0]

        decay_corr = eigen_corr = None
        if opts.skip_comparison[0] is not None:
            if decay_corr:
                decay_corr = '-'.join(['%.1f' % (v)
                                    for v in corr[:10:2]]).replace('0.', '.')
            if eig_corr:
                eigen_corr = '-'.join(['%.2f' % (max(v))
                                    for v in eig_corr[:4]]).replace('0.', '.')
        if not opts.skip_merge:
            cur.execute("""
            insert into MERGE_OUTPUTs
            (Id  , JOBid, Wrkd1Path, Wrkd2Path, Bed1Path, Bed2Path, MergePath)
            values
            (NULL,    %d,        %d,        %d,       %d,       %d,        %d)
            """ % (jobid,    w1path,    w2path,     bed1,     bed2,  outbedid))

        if opts.skip_comparison[0] is not None:
            cur.execute("""
            insert into MERGE_STATs
            (Id  , JOBid, N_columns,   N_filtered, Resolution, reprod, scc, std_scc, decay_corr, eigen_corr, bias1Path, bias2Path)
            values
            (NULL,    %d,        %d,           %d,         %d,     %f,  %f,      %f,       '%s',       '%s',        %d,        %d)
            """ % (jobid,  ncolumns, nbad_columns, opts.reso , reprod, scc,     std, decay_corr, eigen_corr,   biasid1,   biasid2))

        if opts.workdir1:
            if 'tmpdb' in opts and opts.tmpdb:
                # tmp file
                dbfile1 = opts.tmpdb1
                try: # to copy in case read1 was already mapped for example
                    copyfile(path.join(opts.workdir1, 'trace.db'), dbfile1)
                except IOError:
                    pass
            else:
                dbfile1 = path.join(opts.workdir1, 'trace.db')
            tmpcon = lite.connect(dbfile1)
            with tmpcon:
                tmpcur = tmpcon.cursor()
                tmpcur.execute("select Name, PATHid, Count from filter_outputs")
                for name, pathid, count in tmpcur.fetchall():
                    try:
                        res = tmpcur.execute("select Path from PATHs where Id = %d" % (pathid))
                        tmppath = res.fetchall()[0][0]
                    except TypeError:
                        tmppath = None
                    masked1[name] = {'path': tmppath, 'count': count}
            if 'tmpdb' in opts and opts.tmpdb:
                remove(dbfile1)
        if opts.workdir2:
            if 'tmpdb' in opts and opts.tmpdb:
                # tmp file
                dbfile2 = opts.tmpdb2
                try: # to copy in case read2 was already mapped for example
                    copyfile(path.join(opts.workdir2, 'trace.db'), dbfile2)
                except IOError:
                    pass
            else:
                dbfile2 = path.join(opts.workdir2, 'trace.db')
            tmpcon = lite.connect(dbfile2)
            with tmpcon:
                tmpcur = tmpcon.cursor()
                tmpcur.execute("select Name, PATHid, Count from filter_outputs")
                for name, pathid, count in tmpcur.fetchall():
                    try:
                        res = tmpcur.execute("select Path from PATHs where Id = %d" % (pathid))
                        tmppath = res.fetchall()[0][0]
                    except TypeError:
                        tmppath = None
                    masked2[name] = {'path': tmppath, 'count': count}
            if 'tmpdb' in opts and opts.tmpdb:
                remove(dbfile2)

        if not opts.skip_merge:
            for f in masked1:
                if f  != 'valid-pairs':
                    outmask = path.join(opts.workdir, '03_filtered_reads',
                                        'all_r1-r2_intersection_%s.tsv_%s.tsv' % (
                                            param_hash, f.replace(' ', '_')))
                    out = open(outmask, 'w')
                    try:
                        fh = magic_open(path.join(opts.workdir1, masked1[f]['path']))
                    except FileNotFoundError:
                        fh = magic_open(path.join(opts.workdir1, masked1[f]['path'] + '.gz'))
                    except TypeError:
                        continue
                    for line in fh:
                        out.write(line)
                    try:
                        fh = magic_open(path.join(opts.workdir2, masked2[f]['path']))
                    except FileNotFoundError:
                        fh = magic_open(path.join(opts.workdir2, masked2[f]['path'] + '.gz'))
                    for line in fh:
                        out.write(line)
                    add_path(cur, outmask, 'FILTER', jobid, opts.workdir)
                else:
                    if opts.skip_merge:
                        outmask = 'NA'
                    else:
                        outmask = outbed
                try:
                    path_id = get_path_id(cur, outmask, opts.workdir)
                except IndexError:
                    path_id = -1
                cur.execute("""
                insert into FILTER_OUTPUTs
                (Id  , PATHid, Name, Count, JOBid)
                values
                (NULL,     %d, '%s',  '%s',    %d)
                """ % (path_id, f, masked1[f]['count'] + masked2[f]['count'], jobid))

        print_db(cur, 'PATHs')
        print_db(cur, 'JOBs')
        print_db(cur, 'MERGE_OUTPUTs')
        print_db(cur, 'MERGE_STATs')
        print_db(cur, 'FILTER_OUTPUTs')

    if 'tmpdb' in opts and opts.tmpdb:
        # copy back file
        copyfile(dbfile, path.join(opts.workdir, 'trace.db'))
        remove(dbfile)
    # release lock
    try:
        remove(path.join(opts.workdir, '__lock_db'))
    except OSError:
        pass


def load_parameters_fromdb(workdir, jobid, opts, tmpdb):
    if tmpdb:
        dbfile = tmpdb
    else:
        dbfile = path.join(workdir, 'trace.db')
    con = lite.connect(dbfile)
    with con:
        cur = con.cursor()
        if not jobid:
            # get the JOBid of the parsing job
            try:
                cur.execute("""
                select distinct Id from JOBs
                where Type = '%s'
                """ % ('Normalize' if opts.norm else 'Filter'))
                jobids = cur.fetchall()
                parse_jobid = jobids[0][0]
            except IndexError:
                cur.execute("""
                select distinct Id from JOBs
                where Type = '%s'
                """ % ('Filter'))
                jobids = cur.fetchall()
                try:
                    parse_jobid = jobids[0][0]
                except IndexError:
                    parse_jobid = 1
            if len(jobids) > 1:
                found = False
                if opts.norm:
                    cur.execute("""
                    select distinct JOBid from NORMALIZE_OUTPUTs
                    where Resolution = %d
                    """ % (opts.reso))
                    jobs = cur.fetchall()
                    try:
                        parse_jobid = jobs[0][0]
                        found = True
                    except IndexError:
                        found = False
                    if len(jobs ) > 1:
                        found = False
                if not found:
                    raise Exception('ERROR: more than one possible input found, use'
                                    '"tadbit describe" and select corresponding '
                                    'jobid with --jobid')
        else:
            parse_jobid = jobid
        # fetch path to parsed BED files
        # try:
        biases = mreads = reso = None
        if opts.norm:
            try:
                cur.execute("""
                select distinct Path from PATHs
                where paths.jobid = %s and paths.Type = 'BIASES'
                """ % parse_jobid)
                biases = cur.fetchall()[0][0]

                cur.execute("""
                select distinct Path from PATHs
                inner join NORMALIZE_OUTPUTs on PATHs.Id = NORMALIZE_OUTPUTs.Input
                where NORMALIZE_OUTPUTs.JOBid = %d;
                """ % parse_jobid)
                mreads = cur.fetchall()[0][0]

                cur.execute("""
                select distinct Resolution from NORMALIZE_OUTPUTs
                where NORMALIZE_OUTPUTs.JOBid = %d;
                """ % parse_jobid)
                reso = int(cur.fetchall()[0][0])
                if reso != opts.reso:
                    warn('WARNING: input resolution does not match '
                         'the one of the precomputed normalization')
            except IndexError:
                warn('WARNING: normalization not found')
                cur.execute("""
                select distinct path from paths
                inner join filter_outputs on filter_outputs.pathid = paths.id
                where filter_outputs.name = 'valid-pairs' and paths.jobid = %s
                """ % parse_jobid)
                mreads = cur.fetchall()[0][0]
        else:
            cur.execute("""
            select distinct path from paths
            inner join filter_outputs on paths.type = 'HIC_BAM'
            where filter_outputs.name = 'valid-pairs' and paths.jobid = %s
            """ % parse_jobid)
            fetched = cur.fetchall()
            if len(fetched) > 1:
                raise Exception('ERROR: more than one item in the database')
            mreads = fetched[0][0]
        return biases, mreads, reso


def populate_args(parser):
    """
    parse option from call
    """
    parser.formatter_class=lambda prog: HelpFormatter(prog, width=95,
                                                      max_help_position=27)

    glopts = parser.add_argument_group('General options')

    glopts.add_argument('-w', '--workdir', dest='workdir', metavar="PATH",
                        action='store', default=None, type=str,
                        help='''path to a new output folder''')

    glopts.add_argument('-w1', '--workdir1', dest='workdir1', metavar="PATH",
                        action='store', default=None, type=str,
                        help='''path to working directory of the first HiC data
                        sample to merge''')

    glopts.add_argument('-w2', '--workdir2', dest='workdir2', metavar="PATH",
                        action='store', default=None, type=str,
                        help='''path to working directory of the second HiC data
                        sample to merge''')

    glopts.add_argument('--bam1', dest='bam1', metavar="PATH",
                        action='store', default=None, type=str,
                        help='''path to the first TADbit-generated BAM file with
                        all reads (other wise the tool will guess from the
                        working directory database)''')

    glopts.add_argument('--noX', action='store_true', help='no display server (X screen)')

    glopts.add_argument('--bam2', dest='bam2', metavar="PATH",
                        action='store', default=None, type=str,
                        help='''path to the second TADbit-generated BAM file with
                        all reads (other wise the tool will guess from the
                        working directory database)''')

    glopts.add_argument("-C", "--cpus", dest="cpus", type=int,
                        default=cpu_count(), help='''[%(default)s] Maximum number of CPU
                        cores  available in the execution host. If higher
                        than 1, tasks with multi-threading
                        capabilities will enabled (if 0 all available)
                        cores will be used''')

    glopts.add_argument('-r', '--resolution', dest='reso', metavar="INT",
                        action='store', default=None, type=int,
                        help='''resolution at which to do the comparison,
                        and generate the matrices.''')

    glopts.add_argument('--skip_comparison', dest='skip_comparison',
                        default=[None], nargs='+', type=int,
                        help='''[%(default)s] skip the comparison between replicates (faster).
                        Comparisons are performed at 3 levels 1- comparing first
                        diagonals of each experiment (and generating SCC score
                        and standard deviation see
                        https://doi.org/10.1101/gr.220640.117) 2- Comparing the
                        first eigenvectors of input experiments 3- Generates
                        reproducibility score using function from
                        https://doi.org/10.1093/bioinformatics/btx152. ''')

    glopts.add_argument('--skip_merge', dest='skip_merge',
                        action='store_true', default=False,
                        help='''skip the merge of replicates (faster).''')

    glopts.add_argument('--save', dest='save', metavar="STR",
                        action='store', default='genome', nargs='+', type=str,
                        choices=['genome', 'chromosomes'],
                        help='''[%(default)s] save genomic or chromosomic matrix.''')

    glopts.add_argument('--jobid1', dest='jobid1', metavar="INT",
                        action='store', default=None, type=int,
                        help='''Use as input data generated by a job with a given
                        jobid. Use tadbit describe to find out which.''')

    glopts.add_argument('--jobid2', dest='jobid2', metavar="INT",
                        action='store', default=None, type=int,
                        help='''Use as input data generated by a job with a given
                        jobid. Use tadbit describe to find out which.''')

    glopts.add_argument('--force', dest='force', action='store_true',
                        default=False,
                        help='overwrite previously run job')

    glopts.add_argument('--norm', dest='norm', action='store_true',
                        default=False,
                        help='compare normalized matrices')

    glopts.add_argument('--biases1',   dest='biases1', metavar="PATH",
                        action='store', default=None, type=str,
                        help='''path to file with precalculated biases by
                        columns''')

    glopts.add_argument('--biases2',   dest='biases2', metavar="PATH",
                        action='store', default=None, type=str,
                        help='''path to file with precalculated biases by
                        columns''')

    glopts.add_argument('--filter', dest='filter', nargs='+',
                        type=int, metavar='INT', default=[1, 2, 3, 4, 6, 7, 9, 10],
                        choices = list(range(1, 11)),
                        help=("""[%(default)s] Use filters to define a set os
                        valid pair of reads e.g.:
                        '--apply 1 2 3 4 8 9 10'. Where these numbers""" +
                              "correspond to: %s" % (', '.join(
                                  ['%2d: %15s' % (k, MASKED[k]['name'])
                                   for k in MASKED]))))

    glopts.add_argument('--samtools', dest='samtools', metavar="PATH",
                        action='store', default='samtools', type=str,
                        help='''path samtools binary''')

    glopts.add_argument('--tmpdb', dest='tmpdb', action='store', default=None,
                        metavar='PATH', type=str,
                        help='''if provided uses this directory to manipulate the
                        database''')

    parser.add_argument_group(glopts)


def check_options(opts):
    mkdir(opts.workdir)

    # create empty DB if don't exists
    dbpath = path.join(opts.workdir, 'trace.db')
    open(dbpath, 'a').close()

    # for lustre file system....
    if 'tmpdb' in opts and opts.tmpdb:
        dbdir = opts.tmpdb
        # tmp file
        dbfile = 'trace_%s' % (''.join([ascii_letters[int(random() * 52)]
                                        for _ in range(10)]))
        opts.tmpdb = path.join(dbdir, dbfile)
        try:
            copyfile(path.join(opts.workdir, 'trace.db'), opts.tmpdb)
        except IOError:
            pass
        if opts.workdir1:
            # tmp file
            dbfile1 = 'trace1_%s' % (''.join([ascii_letters[int(random() * 52)]
                                              for _ in range(10)]))
            opts.tmpdb1 = path.join(dbdir, dbfile1)
            try:
                copyfile(path.join(opts.workdir1, 'trace.db'), opts.tmpdb1)
            except IOError:
                pass
        if opts.workdir2:
            # tmp file
            dbfile2 = 'trace2_%s' % (''.join([ascii_letters[int(random() * 52)]
                                              for _ in range(10)]))
            opts.tmpdb2 = path.join(dbdir, dbfile2)
            try:
                copyfile(path.join(opts.workdir2, 'trace.db'), opts.tmpdb2)
            except IOError:
                pass
    else:
        if opts.workdir1:
            opts.tmpdb1 = path.join(opts.workdir1, 'trace.db')
        if opts.workdir2:
            opts.tmpdb2 = path.join(opts.workdir2, 'trace.db')

    # resolution needed to compare
    if opts.skip_comparison[0] is not None and not opts.reso:
        raise Exception('ERROR: need to define resolution at which to compare')

    # check if job already run using md5 digestion of parameters
    if already_run(opts):
        if 'tmpdb' in opts and opts.tmpdb:
            remove(path.join(dbdir, dbfile))
            if opts.workdir1:
                remove(path.join(dbdir, dbfile1))
            if opts.workdir2:
                remove(path.join(dbdir, dbfile2))
        exit('WARNING: exact same job already computed, see JOBs table above')

def nice(reso):
    if reso >= 1000000:
        return '%dMb' % (reso / 1000000)
    return '%dkb' % (reso / 1000)
