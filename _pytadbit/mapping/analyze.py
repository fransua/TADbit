"""
18 Nov 2014
"""
from __future__ import print_function

from warnings                     import warn, catch_warnings, simplefilter
from collections                  import OrderedDict

from pysam                        import AlignmentFile
from scipy.stats                  import norm as sc_norm, skew, kurtosis
from scipy.stats                  import pearsonr, spearmanr, linregress
from scipy.sparse.linalg          import eigsh
from numpy.linalg                 import eigh
import numpy as np

try:
    from matplotlib import rcParams
    from matplotlib import pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages
    from matplotlib.colors import LinearSegmentedColormap
except ImportError:
    warn('matplotlib not found\n')


from pytadbit                     import HiC_data
from pytadbit.utils.extraviews    import tadbit_savefig, setup_plot
from pytadbit.utils.tadmaths      import nozero_log_matrix as nozero_log
from pytadbit.utils.tadmaths      import right_double_mad as mad
from pytadbit.parsers.hic_parser  import load_hic_data_from_reads
from pytadbit.utils.extraviews    import nicer
from pytadbit.utils.file_handling import mkdir

try:
    basestring
except NameError:
    basestring = str

def hic_map(data, resolution=None, normalized=False, masked=None,
            by_chrom=False, savefig=None, show=False, savedata=None,
            focus=None, clim=None,  perc_clim=None, cmap='jet', pdf=False, decay=True,
            perc=20, name=None, decay_resolution=None, **kwargs):
    """
    function to retrieve data from HiC-data object. Data can be stored as
    a square matrix, or drawn using matplotlib

    :param data: can be either a path to a file with pre-processed reads
       (filtered or not), or a Hi-C-data object
    :param None resolution: at which to bin the data (try having a dense matrix
       with < 10% of cells with zero interaction counts). Note: not necessary
       if a hic_data object is passed as 'data'.
    :param False normalized: used normalized data, based on precalculated biases
    :param masked: a list of columns to be removed. Usually because to few
       interactions
    :param False by_chrom: data can be stored in a partitioned way. This
       parameter can take the values of:
        * 'intra': one output per each chromosome will be created
        * 'inter': one output per each possible pair of chromosome will be
           created
        * 'all'  : both of the above outputs
    :param None savefig: path where to store the output images. Note that, if
       the by_chrom option is used, then savefig will be the name of the
       directory containing the output files.
    :param None savedata: path where to store the output matrices. Note that, if
       the by_chrom option is used, then savefig will be the name of the
       directory containing the output files.
    :param None focus: can be either two number (i.e.: (1, 100)) specifying the
       start and end position of the sub-matrix to display (start and end, along
       the diagonal of the original matrix); or directly a chromosome name; or
       two chromosome names (i.e.: focus=('chr2, chrX')), in order to store the
       data corresponding to inter chromosomal interactions between these two
       chromosomes
    :param True decay: plot the correlation between genomic distance and
       interactions (usually a decay).
    :param False force_image: force to generate an image even if resolution is
       crazy...
    :param None clim: cutoff for the upper and lower bound in the coloring scale
       of the heatmap. (perc_clim should be set to None)
    :param None perc_clim: cutoff for the upper and lower bound in the coloring scale
       of the heatmap; in percentile. (clim should be set to None)
    :param False pdf: when using the bny_chrom option, to specify the format of
       the stored images
    :param jet cmap: color map to be used for the heatmap; "tadbit" color map is
       also implemented and will use percentiles of the distribution of
       interactions to defines intensities of red.
    :param None decay_resolution: chromatin fragment size to consider when
       calculating decay of the number of interactions with genomic distance.
       Default is equal to resolution of the matrix.
    """
    if isinstance(data, basestring):
        data = load_hic_data_from_reads(data, resolution=resolution, **kwargs)
        if not kwargs.get('get_sections', True) and decay:
            warn('WARNING: not decay not available when get_sections is off.')
            decay = False
    if clim and perc_clim:
        raise Exception('ERROR: only one of clim or perc_clim should be set\n')
    hic_data = data
    resolution = data.resolution
    if not decay_resolution:
        decay_resolution = resolution
    if hic_data.bads and not masked:
        masked = hic_data.bads
    # save and draw the data
    if by_chrom:
        if focus:
            raise Exception('Incompatible options focus and by_chrom\n')
        if savedata:
            mkdir(savedata)
        if savefig:
            mkdir(savefig)
        for i, crm1 in enumerate(hic_data.chromosomes):
            for crm2 in list(hic_data.chromosomes.keys())[i:]:
                if by_chrom == 'intra' and crm1 != crm2:
                    continue
                if by_chrom == 'inter' and crm1 == crm2:
                    continue
                try:
                    subdata = hic_data.get_matrix(focus=(crm1, crm2), normalized=normalized)
                    start1, _ = hic_data.section_pos[crm1]
                    start2, _ = hic_data.section_pos[crm2]
                    masked1 = {}
                    masked2 = {}
                    if focus and hic_data.bads:
                        # rescale masked
                        masked1 = dict([(m - start1, hic_data.bads[m])
                                        for m in hic_data.bads])
                        masked2 = dict([(m - start2, hic_data.bads[m])
                                        for m in hic_data.bads])
                    if masked1 or masked2:
                        for i in range(len(subdata)):
                            if i in masked1:
                                subdata[i] = [float('nan')
                                              for j in range(len(subdata))]
                            for j in range(len(subdata)):
                                if j in masked2:
                                    subdata[i][j] = float('nan')
                    if savedata:
                        hic_data.write_matrix('%s/%s.mat' % (
                            savedata, '_'.join(set((crm1, crm2)))),
                                              focus=(crm1, crm2),
                                              normalized=normalized)
                    if show or savefig:
                        if (len(subdata) > 10000
                            and not kwargs.get('force_image', False)):
                            warn('WARNING: Matrix image not created, more than '
                                 '10000 rows, use a lower resolution to create images')
                            continue
                        draw_map(subdata,
                                 OrderedDict([(k, hic_data.chromosomes[k])
                                              for k in list(hic_data.chromosomes.keys())
                                              if k in [crm1, crm2]]),
                                 hic_data.section_pos,
                                 '%s/%s.%s' % (savefig,
                                               '_'.join(set((crm1, crm2))),
                                               'pdf' if pdf else 'png'),
                                 show, one=True, clim=clim, perc_clim=perc_clim,
                                 cmap=cmap, decay_resolution=decay_resolution,
                                 perc=perc, name=name, cistrans=float('NaN'))
                except ValueError as e:
                    print('Value ERROR: problem with chromosome %s' % crm1)
                    print(str(e))
                except IndexError as e:
                    print('Index ERROR: problem with chromosome %s' % crm1)
                    print(str(e))
    else:
        if savedata:
            hic_data.write_matrix(savedata, focus=focus,
                                  normalized=normalized)
        if show or savefig:
            subdata = hic_data.get_matrix(focus=focus, normalized=normalized)
            if (len(subdata) > 10000 and not kwargs.get('force_image', False)):
                warn('WARNING: Matrix image not created, more than '
                     '10000 rows, use a lower resolution to create images')
                return
            start1 = hic_data._focus_coords(focus)[0]
            if focus and masked:
                # rescale masked
                masked = dict([(m - start1, masked[m]) for m in masked])
            if masked:
                for i in range(len(subdata)):
                    if i in masked:
                        subdata[i] = [float('nan')
                                      for j in range(len(subdata))]
                    for j in range(len(subdata)):
                        if j in masked:
                            subdata[i][j] = float('nan')
            draw_map(subdata,
                     {} if focus else hic_data.chromosomes,
                     hic_data.section_pos, savefig, show,
                     one = True if focus else False, decay=decay,
                     clim=clim, perc_clim=perc_clim, cmap=cmap,
                     decay_resolution=decay_resolution,
                     perc=perc, normalized=normalized,
                     max_diff=kwargs.get('max_diff', None),
                     name=name, cistrans=float('NaN') if focus else
                     hic_data.cis_trans_ratio(normalized,
                                              kwargs.get('exclude', None),
                                              kwargs.get('diagonal', True),
                                              kwargs.get('equals', None)))


def draw_map(data, genome_seq, cumcs, savefig, show, one=False, clim=None,
             perc_clim=None, cmap='jet', decay=False, perc=20, name=None,
             cistrans=None, decay_resolution=10000, normalized=False,
             max_diff=None):
    _ = plt.figure(figsize=(15.,12.5))
    if not max_diff:
        max_diff = len(data)
    ax1 = plt.axes([0.34, 0.08, 0.6, 0.7205])
    ax2 = plt.axes([0.07, 0.65, 0.21, 0.15])
    if decay:
        ax3 = plt.axes([0.07, 0.42, 0.21, 0.15])
        plot_distance_vs_interactions(data, genome_seq=genome_seq, axe=ax3,
                                      resolution=decay_resolution,
                                      max_diff=max_diff, normalized=normalized)
    ax4 = plt.axes([0.34, 0.805, 0.6, 0.04], sharex=ax1)
    ax5 = plt.axes([0.34, 0.845, 0.6, 0.04], sharex=ax1)
    ax6 = plt.axes([0.34, 0.885, 0.6, 0.04], sharex=ax1)
    try:
        minoridata   = np.nanmin(data)
        maxoridata   = np.nanmax(data)
    except AttributeError:
        vals = [i for d in data for i in d if not np.isnan(i)]
        minoridata   = np.min(vals)
        maxoridata   = np.max(vals)
    totaloridata = np.nansum([data[i][j] for i in range(len(data))
                              for j in range(i, len(data[i]))]) # may not be square
    data = nozero_log(data, np.log2)
    vals = np.array([i for d in data for i in d])
    vals = vals[np.isfinite(vals)]

    if perc_clim:
        try:
            clim = np.percentile(vals, perc_clim[0]), np.percentile(vals, perc_clim[1])
        except ValueError:
            clim = None

    mindata = np.nanmin(vals)
    maxdata = np.nanmax(vals)
    diff = maxdata - mindata

    norm = lambda x: (x - mindata) / diff

    posI = 0.01 if not clim else norm(clim[0]) if clim[0] != None else 0.01
    posF = 1.0  if not clim else norm(clim[1]) if clim[1] != None else 1.0

    if cmap == 'tadbit':
        cuts = perc
        cdict = {'red'  : [(0.0,  1.0, 1.0)],
                 'green': [(0.0,  1.0, 1.0)],
                 'blue' : [(0.0,  1.0, 1.0)]}

        for i in np.linspace(posI, posF, cuts, endpoint=False):
            prc = (i / (posF - posI)) / 1.75
            pos = norm(np.percentile(vals, i * 100.))
            # print '%7.4f %7.4f %7.4f %7.4f' % (prc, pos, np.percentile(vals, i * 100.), i)
            cdict['red'  ].append([pos, 1      , 1      ])
            cdict['green'].append([pos, 1 - prc, 1 - prc])
            cdict['blue' ].append([pos, 1 - prc, 1 - prc])
        cdict['red'  ].append([1.0, 1, 1])
        cdict['green'].append([1.0, 0, 0])
        cdict['blue' ].append([1.0, 0, 0])
        cmap  = LinearSegmentedColormap(cmap, cdict)
        clim = None
    else:
        cmap = plt.get_cmap(cmap)
    cmap.set_bad('darkgrey', 1)

    ax1.imshow(data, interpolation='none',
               cmap=cmap, vmin=clim[0] if clim else None, vmax=clim[1] if clim else None)
    size1 = len(data)
    size2 = len(data[0])
    if size1 == size2:
        for i in range(size1):
            for j in range(i, size2):
                if np.isnan(data[i][j]):
                    data[i][j] = 0
                    data[j][i] = 0
    else:
        for i in range(size1):
            for j in range(size2):
                if np.isnan(data[i][j]):
                    data[i][j] = 0
            #data[j][i] = data[i][j]
    try:
        evals, evect = eigh(data)
        sort_perm = evals.argsort()
        evect = evect[sort_perm]
    except:
        evals, evect = None, None
    data = [i for d in data for i in d if np.isfinite(i)]
    gradient = np.linspace(np.nanmin(data),
                           np.nanmax(data), max(size1, size2))
    gradient = np.vstack((gradient, gradient))
    try:
        h  = ax2.hist(data, color='darkgrey', linewidth=2,
                      bins=20, histtype='step', density=True)
    except AttributeError:
        h  = ax2.hist(data, color='darkgrey', linewidth=2,
                      bins=20, histtype='step', normed=True)
    _  = ax2.imshow(gradient, aspect='auto', cmap=cmap,
                    vmin=clim[0] if clim else None, vmax=clim[1] if clim else None,
                    extent=(np.nanmin(data), np.nanmax(data) , 0, max(h[0])))
    if genome_seq:
        for crm in genome_seq:
            ax1.vlines([cumcs[crm][0]-.5, cumcs[crm][1]-.5], cumcs[crm][0]-.5, cumcs[crm][1]-.5,
                       color='w', linestyle='-', linewidth=1, alpha=1)
            ax1.hlines([cumcs[crm][1]-.5, cumcs[crm][0]-.5], cumcs[crm][0]-.5, cumcs[crm][1]-.5,
                       color='w', linestyle='-', linewidth=1, alpha=1)
            ax1.vlines([cumcs[crm][0]-.5, cumcs[crm][1]-.5], cumcs[crm][0]-.5, cumcs[crm][1]-.5,
                       color='k', linestyle='--')
            ax1.hlines([cumcs[crm][1]-.5, cumcs[crm][0]-.5], cumcs[crm][0]-.5, cumcs[crm][1]-.5,
                       color='k', linestyle='--')
        if not one:
            vals = [0]
            keys = ['']
            for crm in genome_seq:
                vals.append(cumcs[crm][0])
                keys.append(crm)
            vals.append(cumcs[crm][1])
            ax1.set_yticks(vals)
            ax1.set_yticklabels('')
            ax1.set_yticks([float(vals[i]+vals[i+1])/2
                            for i in range(len(vals) - 1)], minor=True)
            ax1.set_yticklabels(keys, minor=True)
            for t in ax1.yaxis.get_minor_ticks():
                t.tick1line.set_visible(False)
                t.tick2line.set_visible(False)
    # totaloridata = ''.join([j + ('' if (i+1)%3 else ',') for i, j in enumerate(str(totaloridata)[::-1])])[::-1].strip(',')
    # minoridata = ''.join([j + ('' if (i+1)%3 else ',') for i, j   in enumerate(str(minoridata)[::-1])])[::-1].strip(',')
    # maxoridata = ''.join([j + ('' if (i+1)%3 else ',') for i, j   in enumerate(str(maxoridata)[::-1])])[::-1].strip(',')
    plt.figtext(0.05,0.25, ''.join([
        (name + '\n') if name else '',
        'Number of interactions: %s\n' % str(totaloridata),
        ('' if np.isnan(cistrans) else
         ('Percentage of cis interactions: %.0f%%\n' % (cistrans*100))),
        'Min interactions: %s\n' % (minoridata),
        'Max interactions: %s\n' % (maxoridata)]))
    ax2.set_xlim((np.nanmin(data), np.nanmax(data)))
    ax2.set_ylim((0, max(h[0])))
    ax1.set_xlim ((-0.5, size1 - .5))
    ax1.set_ylim ((-0.5, size2 - .5))
    ax2.set_xlabel('log interaction count')
    # we reduce the number of dots displayed.... we just want to see the shape
    subdata = np.array(list(set([float(int(d*100))/100 for d in data])))
    try:
        normfit = sc_norm.pdf(subdata, np.nanmean(data), np.nanstd(data))
    except AttributeError:
        normfit = sc_norm.pdf(subdata, np.mean(data), np.std(data))
    ax2.plot(subdata, normfit, 'w.', markersize=2.5, alpha=.4)
    ax2.plot(subdata, normfit, 'k.', markersize=1.5, alpha=1)
    ax2.set_title('skew: %.3f, kurtosis: %.3f' % (skew(data),
                                                   kurtosis(data)))
    try:
        ax4.vlines(list(range(size1)), 0, evect[:,-1], color='k')
    except (TypeError, IndexError):
        pass
    ax4.hlines(0, 0, size2, color='red')
    ax4.set_ylabel('E1')
    ax4.set_yticklabels([])
    try:
        ax5.vlines(list(range(size1)), 0, evect[:,-2], color='k')
    except (TypeError, IndexError):
        pass
    ax5.hlines(0, 0, size2, color='red')
    ax5.set_ylabel('E2')
    ax5.set_yticklabels([])
    try:
        ax6.vlines(list(range(size1)), 0, evect[:,-3], color='k')
    except (TypeError, IndexError):
        pass
    ax6.hlines(0, 0, size2, color='red')
    ax6.set_ylabel('E3')
    ax6.set_yticklabels([])
    xticklabels = ax4.get_xticklabels() + ax5.get_xticklabels() + ax6.get_xticklabels()
    plt.setp(xticklabels, visible=False)
    if savefig:
        tadbit_savefig(savefig)
    elif show:
        plt.show()
    plt.close('all')


def plot_distance_vs_interactions(data, min_diff=1, max_diff=1000, show=False,
                                  genome_seq=None, resolution=None, axe=None,
                                  savefig=None, normalized=False,
                                  plot_each_cell=False):
    """
    Plot the number of interactions observed versus the genomic distance between
    the mapped ends of the read. The slope is expected to be around -1, in
    logarithmic scale and between 700 kb and 10 Mb (according to the prediction
    of the fractal globule model).

    :param data: input file name (either tsv or TADbit generated BAM), or
       HiC_data object or list of lists
    :param 10 min_diff: lower limit (in number of bins)
    :param 1000 max_diff: upper limit (in number of bins) to look for
    :param 100 resolution: group reads that are closer than this resolution
       parameter
    :param_hash False plot_each_cell: if false, only the mean distances by bin
       will be represented, otherwise each pair of interactions will be plotted.
    :param None axe: a matplotlib.axes.Axes object to define the plot
       appearance
    :param None savefig: path to a file where to save the image generated;
       if None, the image will be shown using matplotlib GUI (the extension
       of the file name will determine the desired format).

    :returns: slope, intercept and R square of each of the 3 correlations
    """
    if isinstance(data, basestring):
        resolution = resolution or 1
        dist_intr = dict([(i, {})
                          for i in range(min_diff, max_diff)])
        fhandler = open(data)
        line = next(fhandler)
        while line.startswith('#'):
            line = next(fhandler)
        try:
            while True:
                _, cr1, ps1, _, _, _, _, cr2, ps2, _ = line.split('\t', 9)
                if cr1 != cr2:
                    line = next(fhandler)
                    continue
                diff = abs(int(ps1)  // resolution - int(ps2) // resolution)
                if max_diff > diff >= min_diff:
                    try:
                        dist_intr[diff][int(ps1) // resolution] += 1.
                    except KeyError:
                        dist_intr[diff][int(ps1) // resolution] = 1.
                line = next(fhandler)
        except StopIteration:
            pass
        fhandler.close()
        for diff in dist_intr:
            dist_intr[diff] = [dist_intr[diff].get(k, 0)
                               for k in range(max(dist_intr[diff]) - diff)]
    elif isinstance(data, HiC_data):
        resolution = resolution or data.resolution
        dist_intr = dict([(i, []) for i in range(min_diff, max_diff)])
        if normalized:
            get_data = lambda x, y: data[x, y] / data.bias[x] / data.bias[y]
        else:
            get_data = lambda x, y: data[x, y]
        max_diff = min(len(data), max_diff)
        if data.section_pos:
            for crm in data.section_pos:
                for diff in range(min_diff, min(
                    (max_diff, 1 + data.chromosomes[crm]))):
                    for i in range(data.section_pos[crm][0],
                                    data.section_pos[crm][1] - diff):
                        dist_intr[diff].append(get_data(i, i + diff))
        else:
            for diff in range(min_diff, max_diff):
                for i in range(len(data) - diff):
                    if not np.isnan(data[i, i + diff]):
                        dist_intr[diff].append(get_data(i, diff))
    elif isinstance(data, dict):  # if we pass decay/expected dictionary, computes weighted mean
        dist_intr = {}
        for i in range(min_diff, max_diff):
            val = [data[c][i] for c in data
                   if i in data[c] and data[c][i] != data[c].get(i-1, 0)]
            if val:
                dist_intr[i] = [sum(val) / float(len(val))]
            else:
                dist_intr[i] = [0]
    else:
        dist_intr = dict([(i, []) for i in range(min_diff, max_diff)])
        if genome_seq:
            max_diff = min(max(genome_seq.values()), max_diff)
            cnt = 0
            for crm in genome_seq:
                for diff in range(min_diff, min(
                    (max_diff, genome_seq[crm]))):
                    for i in range(cnt, cnt + genome_seq[crm] - diff):
                        if not np.isnan(data[i][i + diff]):
                            dist_intr[diff].append(data[i][i + diff])
                cnt += genome_seq[crm]
        else:
            max_diff = min(len(data), max_diff)
            for diff in range(min_diff, max_diff):
                for i in range(len(data) - diff):
                    if not np.isnan(data[i][i + diff]):
                        dist_intr[diff].append(data[i][i + diff])
    resolution = resolution or 1
    if not axe:
        fig=plt.figure()
        axe = fig.add_subplot(111)
    # remove last part of the plot in case no interaction is count... reduce max_dist
    for diff in range(max_diff - 1, min_diff, -1):
        try:
            if not dist_intr[diff]:
                del(dist_intr[diff])
                max_diff -=1
                continue
        except KeyError:
            max_diff -=1
            continue
        break
    # get_cmap the mean values perc bins
    mean_intr = dict([(i, float(sum(dist_intr[i])) / len(dist_intr[i]))
                      for i in dist_intr if len(dist_intr[i])])
    if plot_each_cell:
        xp, yp = [], []
        for x, y in sorted(list(dist_intr.items()), key=lambda x:x[0]):
            xp.extend([x] * len(y))
            yp.extend(y)
        x = []
        y = []
        for k in range(len(xp)):
            if yp[k]:
                x.append(xp[k])
                y.append(yp[k])
        axe.plot(x, y, color='grey', marker='.', alpha=0.1, ms=1,
                 linestyle='None')
    xp, yp = list(zip(*sorted(list(mean_intr.items()), key=lambda x:x[0])))
    x = []
    y = []
    for k in range(len(xp)):
        if yp[k]:
            x.append(xp[k])
            y.append(yp[k])
    axe.plot(x, y, 'k.', alpha=0.4)
    best = (float('-inf'), 0, 0, 0, 0, 0, 0, 0, 0, 0)
    logx = np.log(x)
    logy = np.log(y)
    ntries = 100
    # set k for better fit
    # for k in xrange(1, ntries/5, ntries/5/5):
    if resolution == 1:
        k = 1
        for i in range(3, ntries-2-k):
            v1 = i * len(x) / ntries
            try:
                a1, b1, r21, _, _ = linregress(logx[ :v1], logy[ :v1])
            except ValueError:
                a1 = b1 = r21 = 0
            r21 *= r21
            for j in range(i + 1 + k, ntries - 2 - k):
                v2 = j * len(x) / ntries
                try:
                    a2, b2, r22, _, _ = linregress(logx[v1+k:v2], logy[v1+k:v2])
                    a3, b3, r23, _, _ = linregress(logx[v2+k:  ], logy[v2+k: ])
                except ValueError:
                    a2 = b2 = r22 = 0
                    a3 = b3 = r23 = 0
                r2 = r21 + r22**2 + r23**2
                if r2 > best[0]:
                    best = (r2, v1, v2, a1, a2, a3,
                            b1, b2, b3, k)
        # plot line of best fit
        (v1, v2,
         a1, a2, a3,
         b1, b2, b3, k) = best[1:]
        yfit1 = lambda xx: np.exp(b1 + a1*np.array (np.log(xx)))
        yfit2 = lambda xx: np.exp(b2 + a2*np.array (np.log(xx)))
        yfit3 = lambda xx: np.exp(b3 + a3*np.array (np.log(xx)))
        axe.plot(x[  :v1], yfit1(x[  :v1] ), color= 'yellow', lw=2,
                 label = r'$\alpha_{%s}=%.2f$' % (
                     '0-0.7 \mathrm{ Mb}' if resolution != 1 else '1', a1))
                 #label = r'$\alpha_1=%.2f$ (0-%d)' % (a1, x[v1]))
        axe.plot(x[v1+k:v2], yfit2(x[v1+k:v2]),  color= 'orange', lw=2,
                 label = r'$\alpha_{%s}=%.2f$' % (
                     '0.7-10 \mathrm{ Mb}' if resolution != 1 else '2', a2))
                 # label = r'$\alpha_2=%.2f$ (%d-%d)' % (a2, x[v1], x[v2]))
        axe.plot(x[v2+k:  ], yfit3(x[v2+k:  ] ), color= 'red'   , lw=2,
                 label = r'$\alpha_{%s}=%.2f$' % (
                     '10 \mathrm{ Mb}-\infty' if resolution != 1 else '3', a3))
                 # label = r'$\alpha_3=%.2f$ (%d-$\infty$)' % (a3, x[v2+k]))
    else:
        # from 0.7 Mb
        v1 = 700000   // resolution
        # to 10 Mb
        v2 = 10000000 // resolution
        try:
            a1, b1, r21, _, _ = linregress(logx[  :v1], logy[  :v1])
        except ValueError:
            a1, b1, r21 = 0, 0, 0
        try:
            a2, b2, r22, _, _ = linregress(logx[v1:v2], logy[v1:v2])
        except ValueError:
            a2, b2, r22 = 0, 0, 0
        try:
            a3, b3, r23, _, _ = linregress(logx[v2:  ], logy[v2:  ])
        except ValueError:
            a3, b3, r23 = 0, 0, 0
        yfit1 = lambda xx: np.exp(b1 + a1*np.array (np.log(xx)))
        yfit2 = lambda xx: np.exp(b2 + a2*np.array (np.log(xx)))
        yfit3 = lambda xx: np.exp(b3 + a3*np.array (np.log(xx)))
        axe.plot(x[  :v1], yfit1(x[  :v1] ), color= 'yellow', lw=2,
                 label = r'$\alpha_{%s}=%.2f$' % (
                     '0-0.7 \mathrm{ Mb}' if resolution != 1 else '1', a1))
                 #label = r'$\alpha_1=%.2f$ (0-%d)' % (a1, x[v1]))
        axe.plot(x[v1:v2], yfit2(x[v1:v2]),  color= 'orange', lw=2,
                 label = r'$\alpha_{%s}=%.2f$' % (
                     '0.7-10 \mathrm{ Mb}' if resolution != 1 else '2', a2))
                 # label = r'$\alpha_2=%.2f$ (%d-%d)' % (a2, x[v1], x[v2]))
        axe.plot(x[v2:  ], yfit3(x[v2:  ] ), color= 'red'   , lw=2,
                 label = r'$\alpha_{%s}=%.2f$' % (
                     '10 \mathrm{ Mb}-\infty' if resolution != 1 else '3', a3))
                 # label = r'$\alpha_3=%.2f$ (%d-$\infty$)' % (a3, x[v2+k]))
    axe.set_ylabel('Log interaction count')
    axe.set_xlabel('Log genomic distance (resolution: %s)' % nicer(resolution))
    axe.legend(loc='lower left', frameon=False)
    axe.set_xscale('log')
    axe.set_yscale('log')
    axe.set_xlim((min_diff, max_diff))
    try:
        with catch_warnings():
            simplefilter("ignore")
            axe.set_ylim((0, max(y)))
    except ValueError:
        pass
    if savefig:
        tadbit_savefig(savefig)
        plt.close('all')
    elif show:
        plt.show()
        plt.close('all')
    return (a1, b1, r21), (a2, b2, r22), (a3, b3, r23)


def plot_iterative_mapping(fnam1, fnam2, total_reads=None, axe=None, savefig=None):
    """
    Plots the number of reads mapped at each step of the mapping process (in the
    case of the iterative mapping, each step is mapping process with a given
    size of fragments).

    :param fnam: input file name
    :param total_reads: total number of reads in the initial FASTQ file
    :param None axe: a matplotlib.axes.Axes object to define the plot
       appearance
    :param None savefig: path to a file where to save the image generated;
       if None, the image will be shown using matplotlib GUI (the extension
       of the file name will determine the desired format).
    :returns: a dictionary with the number of reads per mapped length
    """
    count_by_len = {}
    total_reads = total_reads or 1
    if not axe:
        fig=plt.figure()
        _ = fig.add_subplot(111)
    colors = ['olive', 'darkcyan']
    iteration = False
    for i, fnam in enumerate([fnam1, fnam2]):
        fhandler = open(fnam)
        line = next(fhandler)
        count_by_len[i] = {}
        while line.startswith('#'):
            if line.startswith('# MAPPED '):
                itr, num = line.split()[2:]
                count_by_len[i][int(itr)] = int(num)
            line = next(fhandler)
        if not count_by_len[i]:
            iteration = True
            try:
                while True:
                    _, length, _, _ = line.rsplit('\t', 3)
                    try:
                        count_by_len[i][int(length)] += 1
                    except KeyError:
                        count_by_len[i][int(length)] = 1
                    line = next(fhandler)
            except StopIteration:
                pass
        fhandler.close()
        lengths = sorted(count_by_len[i].keys())
        for k in lengths[::-1]:
            count_by_len[i][k] += sum([count_by_len[i][j]
                                       for j in lengths if j < k])
        plt.plot(lengths, [float(count_by_len[i][l]) / total_reads
                           for l in lengths],
                 label='read' + str(i + 1), linewidth=2, color=colors[i])
    if iteration:
        plt.xlabel('read length (bp)')
    else:
        plt.xlabel('Iteration number')
    if total_reads != 1:
        plt.ylabel('Proportion of mapped reads')
    else:
        plt.ylabel('Number of mapped reads')
    plt.legend(loc=4)
    if savefig:
        tadbit_savefig(savefig)
    elif not axe:
        plt.show()
    plt.close('all')
    return count_by_len


def fragment_size(fnam, savefig=None, nreads=None, max_size=99.9, axe=None,
                 show=False, xlog=False, stats=('median', 'perc_max'),
                 too_large=10_000):
    """
    Plots the distribution of dangling-ends lengths
    :param fnam: input file name
    :param None savefig: path where to store the output images.
    :param 99.9 max_size: top percentage of distances to consider, within the
       top 0.01% are usually found very long outliers.
    :param False xlog: represent x axis in logarithmic scale
    :param ('median', 'perc_max') stats: returns this set of values calculated from the
       distribution of insert/fragment sizes. Possible values are:
        - 'median' median of the distribution
        - 'mean' mean of the distribution
        - 'perc_max' percentil defined by the other parameter 'max_size'
        - 'first_decay' starting from the median of the distribution to the
            first window where 10 consecutive insert sizes are counted less than
            a given value (this given value is equal to the sum of all
            sizes divided by 100 000)
        - 'MAD' Double Median Adjusted Deviation
    :param 10000 too_large: upper bound limit for fragment size to consider
    :param None nreads: number of reads to process (default: all reads)

    :returns: the median value and the percentile inputed as max_size.
    """
    genome_seq = OrderedDict()
    pos = 0
    fhandler = open(fnam)
    for line in fhandler:
        if line.startswith('#'):
            if line.startswith('# CRM '):
                crm, clen = line[6:].split('\t')
                genome_seq[crm] = int(clen)
        else:
            break
        pos += len(line)
    fhandler.seek(pos)
    des = []
    for line in fhandler:
        (crm1, pos1, dir1, _, re1, _,
         crm2, pos2, dir2, _, re2) = line.strip().split('\t')[1:12]
        if re1 == re2 and crm1 == crm2 and dir1 == '1' and dir2 == '0':
            pos1, pos2 = int(pos1), int(pos2)
            des.append(pos2 - pos1)
            if len(des) == nreads:
                break
    des = [i for i in des if i <= too_large]
    fhandler.close()
    if not des:
        warn('ERROR: no dangling-ends found in %s' % (fnam))
        return [float('nan') for _ in stats]

    max_perc = np.percentile(des, max_size)
    perc99   = np.percentile(des, 99)
    perc01   = np.percentile(des, 1)
    perc50   = np.percentile(des, 50)
    meanfr   = np.mean(des)
    perc95   = np.percentile(des, 95)
    perc05   = np.percentile(des, 5)
    to_return = {'median': perc50}
    cutoff = len(des) / 100000.
    count  = 0
    for v in range(int(perc50), int(max(des))):
        if des.count(v) < cutoff:
            count += 1
        else:
            count = 0
        if count >= 10:
            to_return['first_decay'] = v - 10
            break
    else:
        raise ZeroDivisionError('ERROR: no dangling-ends found')
    to_return['perc_max'] = max_perc
    to_return['MAD'] = mad(des)
    to_return['mean'] = meanfr
    if not savefig and not axe and not show:
        return [to_return[k] for k in stats]

    ax = setup_plot(axe, figsize=(10, 5.5))
    desapan = ax.axvspan(perc95, perc99, facecolor='black', alpha=.2,
                         label='1-99%% DEs\n(%.0f-%.0f nts)' % (perc01, perc99))
    ax.axvspan(perc01, perc05, facecolor='black', alpha=.2)
    desapan = ax.axvspan(perc05, perc95, facecolor='black', alpha=.4,
                         label='5-95%% DEs\n(%.0f-%.0f nts)' % (perc05, perc95))
    deshist = ax.hist(des, bins=100, range=(0, max_perc), lw=2,
                      alpha=.5, edgecolor='darkred', facecolor='darkred', label='Dangling-ends')
    ylims   = ax.get_ylim()
    plots   = []
    ax.set_xlabel('Genomic distance between reads')
    ax.set_ylabel('Count')
    ax.set_title('Distribution of dangling-ends ' +
                 'lengths\nmedian: %s (mean: %s), top %.1f%%: %0.f nts' % (
                     int(perc50), int(meanfr), max_size, int(max_perc)))
    if xlog:
        ax.set_xscale('log')
    ax.set_xlim((50, max_perc))
    plt.subplots_adjust(left=0.1, right=0.75)
    ax.legend(bbox_to_anchor=(1.4, 1), frameon=False)
    if savefig:
        tadbit_savefig(savefig)
    elif show and not axe:
        plt.show()
    plt.close('all')
    return [to_return[k] for k in stats]


def plot_genomic_distribution(fnam, first_read=None, resolution=10000,
                              ymax=None, ypercmax=100, yscale=None, savefig=None, show=False,
                              savedata=None, chr_names=None, nreads=None):
    """
    Plot the number of reads in bins along the genome (or along a given
    chromosome).

    :param fnam: input file name
    :param True first_read: uses first read.
    :param 100 resolution: group reads that are closer than this resolution
       parameter
    :param None ymax: upper bound for the y axis
    :param None ypercmax: upper bound for the y axis in percentile of values
    :param None yscale: if set_bad to "log" values will be represented in log2
       scale
    :param None savefig: path to a file where to save the image generated;
       if None, the image will be shown using matplotlib GUI (the extension
       of the file name will determine the desired format).
    :param None savedata: path where to store the output read counts per bin.
    :param None chr_names: can pass a list of chromosome names in case only some
       them the need to be plotted (this option may last even more than default)
    :param None nreads: number of reads to process (default: all reads)

    """
    if first_read:
        warn('WARNING: first_read parameter should no loonger be used.')
    if ymax is not None and ypercmax is not None:
        raise Exception('ERROR: shoud define only ymax or ypercmax, not both')
    distr = {}
    genome_seq = OrderedDict()
    if chr_names:
        chr_names = set(chr_names)
        cond1 = lambda x: x not in chr_names
    else:
        cond1 = lambda x: False
    if nreads:
        cond2 = lambda x: x >= nreads
    else:
        cond2 = lambda x: False
    cond = lambda x, y: cond1(x) or cond2(y)
    count = 0
    pos = 0
    fhandler = open(fnam)
    for line in fhandler:
        if line.startswith('#'):
            if line.startswith('# CRM '):
                crm, clen = line[6:].split('\t')
                genome_seq[crm] = int(clen)
        else:
            break
        pos += len(line)
    fhandler.seek(pos)
    for line in fhandler:
        line = line.strip().split('\t')
        count += 1
        for idx1, idx2 in ((1, 3), (7, 9)):
            crm, pos = line[idx1:idx2]
            if cond(crm, count):
                if cond2(count):
                    break
                continue
            pos = int(pos) // resolution
            try:
                distr[crm][pos] += 1
            except KeyError:
                try:
                    distr[crm][pos] = 1
                except KeyError:
                    distr[crm] = {pos: 1}
        else:
            continue
        break
    fhandler.close()
    if savefig or show:
        fig = plt.figure(figsize=(8, 1.5 + 0.3 * len(
            chr_names if chr_names else list(distr.keys()))), facecolor='w')

    max_y = np.nanpercentile([v for c in distr for v in distr[c].values()], ypercmax)
    if ymax is None:
        ylim = 0, max_y
    max_x = max([len(list(distr[c].values())) for c in distr])
    ncrms = len(chr_names if chr_names else genome_seq if genome_seq else distr)
    data = {}
    for i, crm in enumerate(chr_names if chr_names else genome_seq
                            if genome_seq else distr):
        try:
            # data[crm] = [distr[crm].get(j, 0) for j in xrange(max(distr[crm]))]  # genome_seq[crm]
            data[crm] = [distr[crm].get(j, 0)
                         for j in range(genome_seq[crm] // resolution + 1)]
            if savefig or show:
                axe = plt.subplot(ncrms, 1, i + 1)
                axe.fill_between(list(range(genome_seq[crm] // resolution + 1)), data[crm],
                         color='tab:red', lw=1.5, alpha=0.7)
                plt.axis('off')
                # horizontal grid
                for p in [ylim[0], (ylim[1] + ylim[0]) / 2, ylim[1]]:
                    axe.plot([0, genome_seq[crm] / resolution], [p, p], color='k', ls='-', lw=1, alpha=0.3)
                for pos, h in enumerate(range(0, genome_seq[crm] // resolution, 10_000_000 // resolution)):
                    axe.axvline(h, color='tab:grey', alpha=0.4  if pos % 5 else 0.6, lw=1 if pos % 5 else 2)
                axe.text(- genome_seq[crm] / (resolution * 500), (ylim[1] + ylim[0]) / 2, crm, 
                         rotation=0, ha='right', va='center', size=12)
                if yscale:
                    plt.yscale(yscale)
        except KeyError:
            pass
        if savefig or show:
            plt.xlim((0, max_x))
            plt.ylim(ylim or (0, max_y))
    if yscale == 'log':
        yb = ylim[0]
        ybb = ylim[0]
        ybbb = ylim[0]
        ybbbb = ylim[0]
    else:
        yb = ylim[0] - abs(ylim[1] - ylim[0]) * 0.2
        ybb = ylim[0] - abs(ylim[1] - ylim[0]) * 0.35
        ybbb = ylim[0] - abs(ylim[1] - ylim[0]) * 0.45
        ybbbb = ylim[0] - abs(ylim[1] - ylim[0]) * 0.55
    axe.plot([0, max_x], [yb, yb], ls='-', color='k', clip_on=False)
    for pos, h in enumerate(range(0, max_x, 10_000_000 // resolution)):
        axe.plot([h, h], [yb, ybb if pos % 5 else ybbb], ls='-', color='k', 
                 lw=1  if pos % 5 else 2, clip_on=False)
        if not pos % 5:
            axe.text(h, ybbbb, f"{h * resolution // 1_000_000}Mb", va='top', ha='center')
    if savefig or show:
        plt.suptitle(
            f"""Resolution (binning): {resolution:,} nts
Y range (counts per bin): {int(ylim[0]):,} - {int(ylim[1]):,}
Number of reads{' (all)' if nreads is None else ''}: {count:,}""", 
                    size=12, ha="left", y=0.3, x=0.5)
    if savefig:
        plt.tight_layout()
        tadbit_savefig(savefig)
        if not show:
            plt.close('all')
    elif show:
        plt.tight_layout()
        # plt.show()

    if savedata:
        out = open(savedata, 'w')
        out.write('# CRM\tstart-end\tcount\n')
        out.write('\n'.join('%s\t%d-%d\t%d' % (c, (i * resolution) + 1,
                                               ((i + 1) * resolution), v)
                            for c in data for i, v in enumerate(data[c])))
        out.write('\n')
        out.close()

def _unitize(vals):
    return np.argsort(vals) / float(len(vals))


def correlate_matrices(hic_data1, hic_data2, max_dist=10, intra=False, axe=None,
                       savefig=None, show=False, savedata=None, min_dist=1,
                       normalized=False, remove_bad_columns=True, **kwargs):
    """
    Compare the interactions of two Hi-C matrices at a given distance,
       with Spearman rank correlation.

    Also computes the SCC reproducibility score as in HiCrep (see
       https://doi.org/10.1101/gr.220640.117). It's implementation is inspired
       by the version implemented in dryhic by Enrique Vidal
       (https://github.com/qenvio/dryhic).


    :param hic_data1: Hi-C-data object
    :param hic_data2: Hi-C-data object
    :param 1 resolution: to be used for scaling the plot
    :param 10 max_dist: maximum distance from diagonal (e.g. 10 mean we will
       not look further than 10 times the resolution)
    :param 1 min_dist: minimum distance from diagonal (set to 0 to reproduce
       result from HicRep)
    :param None savefig: path to save the plot
    :param False intra: only takes into account intra-chromosomal contacts
    :param False show: displays the plot
    :param False normalized: use normalized data
    :param True remove_bads: computes the union of bad columns between samples
       and exclude them from the comparison

    :returns: list of correlations, list of genomic distances, SCC and standard
       deviation of SCC
    """
    spearmans = []
    pearsons = []
    dists = []
    weigs = []

    if normalized:
        get_the_guy1 = lambda i, j: (hic_data1[j, i] / hic_data1.bias[i] /
                                     hic_data1.bias[j])
        get_the_guy2 = lambda i, j: (hic_data2[j, i] / hic_data2.bias[i] /
                                     hic_data2.bias[j])
    else:
        get_the_guy1 = lambda i, j: hic_data1[j, i]
        get_the_guy2 = lambda i, j: hic_data2[j, i]

    if remove_bad_columns:
        # union of bad columns
        bads = hic_data1.bads.copy()
        bads.update(hic_data2.bads)

    if (intra and hic_data1.sections and hic_data2.sections and
        hic_data1.sections == hic_data2.sections):
        for dist in range(1, max_dist + 1):
            diag1 = []
            diag2 = []
            for crm in hic_data1.section_pos:
                for j in range(hic_data1.section_pos[crm][0],
                                hic_data1.section_pos[crm][1] - dist):
                    i = j + dist
                    if j in bads or i in bads:
                        continue
                    diag1.append(get_the_guy1(i, j))
                    diag2.append(get_the_guy2(i, j))
            spearmans.append(spearmanr(diag1, diag2)[0])
            pearsons.append(spearmanr(diag1, diag2)[0])
            r1 = _unitize(diag1)
            r2 = _unitize(diag2)
            weigs.append((np.var(r1, ddof=1) *
                          np.var(r2, ddof=1))**0.5 * len(diag1))
            dists.append(dist)
    else:
        if intra:
            warn('WARNING: hic_dta does not contain chromosome coordinates, ' +
                 'intra set to False')
        for dist in range(min_dist, max_dist + min_dist):
            diag1 = []
            diag2 = []
            for j in range(len(hic_data1) - dist):
                i = j + dist
                if j in bads or i in bads:
                    continue
                diag1.append(get_the_guy1(i, j))
                diag2.append(get_the_guy2(i, j))
            spearmans.append(spearmanr(diag1, diag2)[0])
            pearsons.append(pearsonr(diag1, diag2)[0])
            r1 = _unitize(diag1)
            r2 = _unitize(diag2)
            weigs.append((np.var(r1, ddof=1) *
                          np.var(r2, ddof=1))**0.5 * len(diag1))
            dists.append(dist)
    # compute scc
    # print pearsons
    # print weigs
    tot_weigth = sum(weigs)
    scc = sum(pearsons[i] * weigs[i] / tot_weigth
              for i in range(len(pearsons)))
    var_corr = np.var(pearsons, ddof=1)
    std = (sum(weigs[i]**2 for i in range(len(pearsons))) * var_corr /
           sum(weigs)**2)**0.5
    # plot
    if show or savefig or axe:
        if not axe:
            fig = plt.figure()
            axe = fig.add_subplot(111)
            given_axe = False
        else:
            given_axe = True
        axe.plot(dists, spearmans, color='orange', linewidth=3, alpha=.8)
        axe.set_xlabel('Genomic distance in bins')
        axe.set_ylabel('Spearman rank correlation')
        axe.set_xlim((0, dists[-1]))
        if savefig:
            tadbit_savefig(savefig)
        if show:
            plt.show()
        if not given_axe:
            plt.close('all')
    if savedata:
        out = open(savedata, 'w')
        out.write('# genomic distance\tSpearman rank correlation\n')
        for i in range(len(spearmans)):
            out.write('%s\t%s\n' % (dists[i], spearmans[i]))
        out.close()
    if kwargs.get('get_bads', False):
        return spearmans, dists, scc, std, bads
    return spearmans, dists, scc, std

def scc(mat1, mat2, max_dist=50, min_dist=1):
    
    pearsons=[]
    dists = []
    weigs=[]

    for dist in range(min_dist, max_dist + min_dist):
        diag1 = []
        diag2 = []
        for j in range(len(mat1) - dist):
            i = j + dist
            if np.isnan(mat1[i][j]) or np.isnan(mat1[i][j]):
                continue
            diag1.append(mat1[i][j])
            diag2.append(mat2[i][j])
        if len(diag1) > 1:
            with catch_warnings():
                simplefilter("ignore")
                p_corr = pearsonr(diag1, diag2)[0]
            if not np.isnan(p_corr):
                pearsons.append(p_corr)
                r1 = _unitize(diag1)
                r2 = _unitize(diag2)
                weigs.append((np.var(r1, ddof=1) *
                              np.var(r2, ddof=1))**0.5 * len(diag1))
                dists.append(dist)
    if len(pearsons) == 0:
        return 0, 0
    tot_weigth = sum(weigs)
    scc = sum(pearsons[i] * weigs[i] / tot_weigth
              for i in range(len(pearsons)))
    var_corr = np.var(pearsons, ddof=1)
    std = (sum(weigs[i]**2 for i in range(len(pearsons))) * var_corr /
           sum(weigs)**2)**0.5

    return scc, std

def _evec_dist(v1,v2):
    d1=np.dot(v1-v2,v1-v2)
    d2=np.dot(v1+v2,v1+v2)
    if d1<d2:
        d=d1
    else:
        d=d2
    return np.sqrt(d)


def _get_Laplacian(M):
    S=M.sum(1)
    i_nz=np.where(S>0)[0]
    S=S[i_nz]
    M=(M[i_nz].T)[i_nz].T
    S=1/np.sqrt(S)
    M=S*M
    M=(S*M.T).T
    n=np.size(S)
    M=np.identity(n)-M
    M=(M+M.T)/2
    return M


def get_ipr(evec):
    ipr=1.0/(evec*evec*evec*evec).sum()
    return ipr


def get_reproducibility(hic_data1, hic_data2, num_evec, verbose=True,
                        normalized=False, remove_bad_columns=True):
    """
    Compute reproducibility score similarly to HiC-spector
       (https://doi.org/10.1093/bioinformatics/btx152)

    :param hic_data1: Hi-C-data object
    :param hic_data2: Hi-C-data object
    :param 20 num_evec: number of eigenvectors to compare

    :returns: reproducibility score (bellow 0.5 ~ different cell types)
    """
    M1 = hic_data1.get_matrix(normalized=normalized)
    M2 = hic_data2.get_matrix(normalized=normalized)

    if remove_bad_columns:
        # union of bad columns
        bads = hic_data1.bads.copy()
        bads.update(hic_data2.bads)
        # remove them form both matrices
        for bad in sorted(bads, reverse=True):
            del(M1[bad])
            del(M2[bad])
            for i in range(len(M1)):
                _ = M1[i].pop(bad)
                _ = M2[i].pop(bad)

    M1 = np.matrix(M1)
    M2 = np.matrix(M2)

    k1=np.sign(M1.A).sum(1)
    d1=np.diag(M1.A)
    kd1=~((k1==1)*(d1>0))
    k2=np.sign(M2.A).sum(1)
    d2=np.diag(M2.A)
    kd2=~((k2==1)*(d2>0))
    iz=np.nonzero((k1+k2>0)*(kd1>0)*(kd2>0))[0]
    M1b=(M1[iz].A.T)[iz].T
    M2b=(M2[iz].A.T)[iz].T

    i_nz1=np.where(M1b.sum(1)>0)[0]
    i_nz2=np.where(M2b.sum(1)>0)[0]
    i_z1=np.where(M1b.sum(1)==0)[0]
    i_z2=np.where(M2b.sum(1)==0)[0]

    M1b_L=_get_Laplacian(M1b)
    M2b_L=_get_Laplacian(M2b)

    a1, b1=eigsh(M1b_L,k=num_evec,which="SM")
    a2, b2=eigsh(M2b_L,k=num_evec,which="SM")

    b1_extend=np.zeros((np.size(M1b,0),num_evec))
    b2_extend=np.zeros((np.size(M2b,0),num_evec))
    for i in range(num_evec):
        b1_extend[i_nz1,i]=b1[:,i]
        b2_extend[i_nz2,i]=b2[:,i]

    ipr_cut=5
    ipr1=np.zeros(num_evec)
    ipr2=np.zeros(num_evec)
    for i in range(num_evec):
        ipr1[i]=get_ipr(b1_extend[:,i])
        ipr2[i]=get_ipr(b2_extend[:,i])

    b1_extend_eff=b1_extend[:,ipr1>ipr_cut]
    b2_extend_eff=b2_extend[:,ipr2>ipr_cut]
    num_evec_eff=min(np.size(b1_extend_eff,1),np.size(b2_extend_eff,1))

    evd=np.zeros(num_evec_eff)
    for i in range(num_evec_eff):
        evd[i]=_evec_dist(b1_extend_eff[:,i],b2_extend_eff[:,i])

    Sd=evd.sum()
    l=np.sqrt(2)
    evs=abs(l-Sd/num_evec_eff)/l

    N = float(M1.shape[1])
    if verbose:
        if (np.sum(ipr1>N/100)<=1)|(np.sum(ipr2>N/100)<=1):
            print("at least one of the maps does not look like typical Hi-C maps")
        else:
            print("size of maps: %d" %(np.size(M1,0)))
            print("reproducibility score: %6.3f " %(evs))
            print("num_evec_eff: %d" %(num_evec_eff))

    return evs


def eig_correlate_matrices(hic_data1, hic_data2, nvect=6, normalized=False,
                           savefig=None, show=False, savedata=None,
                           remove_bad_columns=True, **kwargs):
    """
    Compare the interactions of two Hi-C matrices using their 6 first
    eigenvectors, with Pearson correlation

    :param hic_data1: Hi-C-data object
    :param hic_data2: Hi-C-data object
    :param 6 nvect: number of eigenvectors to compare
    :param None savefig: path to save the plot
    :param False show: displays the plot
    :param False normalized: use normalized data
    :param True remove_bads: computes the union of bad columns between samples
       and exclude them from the comparison
    :param kwargs: any argument to pass to matplotlib imshow function

    :returns: matrix of correlations
    """
    data1 = hic_data1.get_matrix(normalized=normalized)
    data2 = hic_data2.get_matrix(normalized=normalized)
    ## reduce matrices to remove bad columns
    if remove_bad_columns:
        # union of bad columns
        bads = hic_data1.bads.copy()
        bads.update(hic_data2.bads)
        # remove them form both matrices
        for bad in sorted(bads, reverse=True):
            del(data1[bad])
            del(data2[bad])
            for i in range(len(data1)):
                _ = data1[i].pop(bad)
                _ = data2[i].pop(bad)
    # get the log
    data1 = nozero_log(data1, np.log2)
    data2 = nozero_log(data2, np.log2)
    # get the eigenvectors
    ev1, evect1 = eigh(data1)
    ev2, evect2 = eigh(data2)
    corr = [[0 for _ in range(nvect)] for _ in range(nvect)]
    # sort eigenvectors according to their eigenvalues => first is last!!
    sort_perm = ev1.argsort()
    ev1.sort()
    evect1 = evect1[sort_perm]
    sort_perm = ev2.argsort()
    ev2.sort()
    evect2 = evect2[sort_perm]
    # calculate Pearson correlation
    for i in range(nvect):
        for j in range(nvect):
            corr[i][j] = abs(pearsonr(evect1[:,-i-1],
                                      evect2[:,-j-1])[0])
    # plot
    axe    = plt.axes([0.1, 0.1, 0.6, 0.8])
    cbaxes = plt.axes([0.85, 0.1, 0.03, 0.8])
    if show or savefig:
        im = axe.imshow(corr, interpolation="nearest",origin='lower', **kwargs)
        axe.set_xlabel('Eigen Vectors exp. 1')
        axe.set_ylabel('Eigen Vectors exp. 2')
        axe.set_xticks(list(range(nvect)))
        axe.set_yticks(list(range(nvect)))
        axe.set_xticklabels(list(range(1, nvect + 1)))
        axe.set_yticklabels(list(range(1, nvect + 1)))
        axe.xaxis.set_tick_params(length=0, width=0)
        axe.yaxis.set_tick_params(length=0, width=0)

        cbar = plt.colorbar(im, cax = cbaxes )
        cbar.ax.set_ylabel('Pearson correlation', rotation=90*3,
                           verticalalignment='bottom')
        axe2 = axe.twinx()
        axe2.set_yticks(list(range(nvect)))
        axe2.set_yticklabels(['%.1f' % (e) for e in ev2[-nvect:][::-1]])
        axe2.set_ylabel('corresponding Eigen Values exp. 2', rotation=90*3,
                        verticalalignment='bottom')
        axe2.set_ylim((-0.5, nvect - 0.5))
        axe2.yaxis.set_tick_params(length=0, width=0)

        axe3 = axe.twiny()
        axe3.set_xticks(list(range(nvect)))
        axe3.set_xticklabels(['%.1f' % (e) for e in ev1[-nvect:][::-1]])
        axe3.set_xlabel('corresponding Eigen Values exp. 1')
        axe3.set_xlim((-0.5, nvect - 0.5))
        axe3.xaxis.set_tick_params(length=0, width=0)

        axe.set_ylim((-0.5, nvect - 0.5))
        axe.set_xlim((-0.5, nvect - 0.5))
        if savefig:
            tadbit_savefig(savefig)
        if show:
            plt.show()
        plt.close('all')

    if savedata:
        out = open(savedata, 'w')
        out.write('# ' + '\t'.join(['Eigen Vector %s'% i
                                    for i in range(nvect)]) + '\n')
        for i in range(nvect):
            out.write('\t'.join([str(corr[i][j])
                                 for j in range(nvect)]) + '\n')
        out.close()
    if kwargs.get('get_bads', False):
        return corr, bads
    else:
        return corr

def plot_rsite_reads_distribution(reads_file, outprefix, window=20,
        maxdist=1000):
    de_right={}
    de_left={}
    print("process reads")
    fl=open(reads_file)
    while True:
        line=next(fl)
        if not line.startswith('#'):
            break
    nreads=0
    try:
        while True:
            nreads += 1
            if nreads % 1000000 == 0:
                print(nreads)
            try:
                _, n1, sb1, sd1, l1, ru1, rd1, n2, sb2, sd2, l2, ru2, rd2\
                        = line.split()
                sb1, sd1, l1, ru1, rd1, sb2, sd2, l2, ru2, rd2 = \
                        list(map(int, [sb1, sd1, l1, ru1, rd1, sb2, sd2, l2,
                            ru2, rd2]))
            except ValueError:
                print(line)
                raise ValueError("line is not the right format!")
            if n1 != n2:
                line=next(fl)
                continue
            #read1 ahead of read2
            if sb1 > sb2:
                sb1, sd1, l1, ru1, rd1, sb2, sd2, l2, ru2, rd2 = \
                    sb2, sd2, l2, ru2, rd2, sb1, sd1, l1, ru1, rd1
            #direction always -> <-
            if not (sd1 == 1 and sd2 == 0):
                line=next(fl)
                continue
            #close to the diagonal
            if sb2-sb1 > maxdist:
                line=next(fl)
                continue
            #close to RE 1
            if abs(sb1-ru1) < abs(sb1-rd1):
                rc1=ru1
            else:
                rc1=rd1
            pos=sb1-rc1
            if abs(pos)<=window:
                if not pos in de_right:
                    de_right[pos]=0
                de_right[pos]+=1
            #close to RE 2
            if abs(sb2-ru2) < abs(sb2-rd2):
                rc2=ru2
            else:
                rc2=rd2
            pos=sb2-rc2
            if abs(pos)<=window:
                if not pos in de_left:
                    de_left[pos]=0
                de_left[pos]+=1
            line=next(fl)
    except StopIteration:
        pass
    print("   finished processing {} reads".format(nreads))

    #transform to arrays
    ind = list(range(-window,window+1))
    de_r = [de_right.get(x,0) for x in ind]
    de_l = [de_left.get(x,0) for x in ind]

    #write to files
    print("write to files")
    fl=open(outprefix+'_count.dat','w')
    fl.write('#dist\tX~~\t~~X\n')
    for i,j,k in zip(ind,de_r, de_l):
        fl.write('{}\t{}\t{}\n'.format(i, j, k))

    #write plot
    rcParams.update({'font.size': 10})
    pp = PdfPages(outprefix+'_plot.pdf')
    ind = np.array(ind)
    width = 1
    pr = plt.bar(ind-0.5, de_r, width, color='r')
    pl = plt.bar(ind-0.5, de_l, width, bottom=de_r, color='b')
    plt.ylabel("Count")
    plt.title("Histogram of counts around cut site")
    plt.xticks(ind[::2], rotation="vertical")
    plt.legend((pl[0], pr[0]), ("~~X", "X~~"))
    plt.gca().set_xlim([-window-1,window+1])
    pp.savefig()
    pp.close()


def moving_average(a, n=3):
    ret = np.cumsum(a, dtype=float)
    ret[n:] = ret[n:] - ret[:-n]
    return ret[n - 1:] / n


def plot_diagonal_distributions(reads_file, outprefix, ma_window=20,
        maxdist=800, de_left=[-2,3], de_right=[0,5]):
    rbreaks={}
    rejoined={}
    des={}
    print("process reads")
    fl=open(reads_file)
    while True:
        line=next(fl)
        if not line.startswith('#'):
            break
    nreads=0
    try:
        while True:
            nreads += 1
            if nreads % 1000000 == 0:
                print(nreads)
            try:
                _, n1, sb1, sd1, _, ru1, rd1, n2, sb2, sd2, _, ru2, rd2\
                        = line.split()
                sb1, sd1, ru1, rd1, sb2, sd2, ru2, rd2 = \
                        list(map(int, [sb1, sd1, ru1, rd1, sb2, sd2, ru2, rd2]))
            except ValueError:
                print(line)
                raise ValueError("line is not the right format!")
            if n1 != n2:
                line=next(fl)
                continue
            #read1 ahead of read2
            if sb1 > sb2:
                sb1, sd1, ru1, rd1, sb2, sd2, ru2, rd2 = \
                    sb2, sd2, ru2, rd2, sb1, sd1, ru1, rd1
            #direction always -> <-
            if not (sd1 == 1 and sd2 == 0):
                line=next(fl)
                continue
            mollen = sb2-sb1
            if mollen > maxdist:
                line=next(fl)
                continue
            #DE1
            if abs(sb1-ru1) < abs(sb1-rd1):
                rc1=ru1
            else:
                rc1=rd1
            pos=sb1-rc1
            if pos in de_right:
                if not mollen in des:
                    des[mollen]=0
                des[mollen]+=1
                line=next(fl)
                continue
            #DE2
            if abs(sb2-ru2) < abs(sb2-rd2):
                rc2=ru2
            else:
                rc2=rd2
            pos=sb2-rc2
            if pos in de_left:
                if not mollen in des:
                    des[mollen]=0
                des[mollen]+=1
                line=next(fl)
                continue
            #random: map on same fragment
            if rd1 == rd2:
                if not mollen in rbreaks:
                    rbreaks[mollen]=0
                rbreaks[mollen]+=1
                line=next(fl)
                continue
            #rejoined ends
            if not mollen in rejoined:
                rejoined[mollen]=0
            rejoined[mollen]+=1
            line=next(fl)
    except StopIteration:
        pass
    print("   finished processing {} reads".format(nreads))

    #transform to arrays
    maxlen = max(max(rejoined),max(des),max(rbreaks))
    ind = list(range(1,maxlen+1))
    des = [des.get(x,0) for x in ind]
    rbreaks = [rbreaks.get(x,0) for x in ind]
    rejoined = [rejoined.get(x,0) for x in ind]
    #reweight corner for rejoined
    rejoined = [x**.5 * rejoined[x-1]/x for x in ind]

    #write to files
    print("write to files")
    fl=open(outprefix+'_count.dat','w')
    fl.write('#dist\trbreaks\tdes\trejoined\n')
    for i,j,k,l in zip(ind,rbreaks,des,rejoined):
        fl.write('{}\t{}\t{}\t{}\n'.format(i, j, k, l))

    #transform data a bit more
    ind, des, rbreaks, rejoined = \
            [moving_average(np.array(x), ma_window) for x in [ind, des, rbreaks, rejoined]]
    des, rbreaks, rejoined = [x/float(x.sum()) for x in [des, rbreaks, rejoined]]
    np.insert(ind,0,0)
    np.insert(des,0,0)
    np.insert(rbreaks,0,0)
    np.insert(rejoined,0,0)

    #write plot
    pp = PdfPages(outprefix+'_plot.pdf')
    rcParams.update({'font.size': 10})
    pde = plt.fill_between(ind, des, 0, color='r', alpha=0.5)
    prb = plt.fill_between(ind, rbreaks, 0, color='b', alpha=0.5)
    prj = plt.fill_between(ind, rejoined, 0, color='y', alpha=0.5)
    plt.ylabel("Normalized count")
    plt.ylabel("Putative DNA molecule length")
    plt.title("Histogram of counts close to the diagonal")
    #plt.xticks(ind[::10], rotation="vertical")
    plt.legend((prb, pde, prj), ("Random breaks", "Dangling ends",
        "Rejoined"))
    plt.gca().set_xlim([0,maxlen])
    pp.savefig()
    pp.close()


def plot_strand_bias_by_distance(fnam, nreads=1000000, valid_pairs=True,
                                 half_step=20, half_len=2000,
                                 full_step=500, full_len=50000, savefig=None):
    """
    Classify reads into four categories depending on the strand on which each
    of its end is mapped, and plots the proportion of each of these categories
    in function of the genomic distance between them.

    Only full mapped reads mapped on two diferent restriction fragments (still
    same chromosome) are considered.

    The four categories are:
       - Both read-ends mapped on the same strand (forward)
       - Both read-ends mapped on the same strand (reverse)
       - Both read-ends mapped on the different strand (facing), like extra-dangling-ends
       - Both read-ends mapped on the different strand (opposed), like extra-self-circles

    :params fnam: path to tsv file with intersection of mapped ends
    :params True valid_pairs: consider only read-ends mapped
       on different restriction fragments. If False, considers only read-ends
       mapped on the same restriction fragment.
    :params 1000000 nreads: number of reads used to plot (if None, all will be used)
    :params 20 half_step: binning for the first part of the plot
    :params 2000 half_len: maximum distance for the first part of the plot
    :params 500 full_step:  binning for the second part of the plot
    :params 50000 full_len: maximum distance for the second part of the plot
    :params None savefig: path to save figure
    """
    max_len = 100000

    genome_seq = OrderedDict()
    pos = 0
    fhandler = open(fnam)
    for line in fhandler:
        if line.startswith('#'):
            if line.startswith('# CRM '):
                crm, clen = line[6:].split('\t')
                genome_seq[crm] = int(clen)
        else:
            break
        pos += len(line)
    fhandler.seek(pos)

    names = ['<== <== both reverse',
             '<== ==> opposed (Extra-self-circles)',
             '==> <== facing (Extra-dangling-ends)',
             '==> ==> both forward']
    
    dirs = np.zeros((4, max_len))
    
    iterator = (next(fhandler) for _ in range(nreads)) if nreads else fhandler
    
    if valid_pairs:
        comp_re = lambda x, y: x != y
    else:
        comp_re = lambda x, y: x == y

    for line in iterator:
        (crm1, pos1, dir1, len1, re1, _,
         crm2, pos2, dir2, len2, re2) = line.strip().split('\t')[1:12]
        pos1, pos2 = int(pos1), int(pos2)
        if pos2 < pos1:
            pos2, pos1 = pos1, pos2
            dir2, dir1 = dir1, dir2
            len2, len1 = len1, len2
        dir1, dir2 = int(dir1), int(dir2)
        len1, len2 = int(len1), int(len2)
        if dir1 == 0:
            pos1 -= len1
        if dir2 == 1:
            pos2 += len2
        diff = pos2 - pos1
        # only ligated; same chromsome; bellow max_dist; not multi-contact
        if comp_re(re1, re2) and crm1 == crm2 and diff < max_len and len1 == len2:
            dir1, dir2 = dir1 * 2, dir2
            dirs[dir1 + dir2][diff] += 1

    sum_dirs = dirs.sum(axis=0)

    plt.figure(figsize=(14, 9))
    if full_step:
        axLp = plt.subplot2grid((3, 2), (0, 0), rowspan=2)
        axLb = plt.subplot2grid((3, 2), (2, 0), sharex=axLp)

        axRp = plt.subplot2grid((3, 2), (0, 1), rowspan=2, sharey=axLp)
        axRb = plt.subplot2grid((3, 2), (2, 1), sharex=axRp, sharey=axLb)
    else:
        axLp = plt.subplot2grid((3, 1), (0, 0), rowspan=2)
        axLb = plt.subplot2grid((3, 1), (2, 0), sharex=axLp)

    for d in range(4):
        axLp.plot([sum(dirs[d,i:i + half_step]) / (sum(sum_dirs[i:i + half_step]) + 0.1)
                   for i in range(0, half_len - half_step, half_step)],
                  alpha=0.7, label=names[d])

    axLp.set_ylim(0, 1)
    axLp.set_yticks([0, 0.25, 0.5, 0.75, 1])
    axLp.set_xlim(0, half_len / half_step)
    axLp.set_xticks(axLp.get_xticks()[:-1])
    axLp.set_xticklabels([str(int(i)) for i in axLp.get_xticks() * half_step])
    axLp.grid()
    if full_step:
        axLp.spines['right'].set_visible(False)
        plt.setp(axLp.get_xticklabels(), visible=False)
        axLb.spines['right'].set_visible(False)

    axLp.set_ylabel('Proportion of reads in each category')

    axLb.bar(list(range(0, half_len // half_step - 1)),
             [sum(sum_dirs[i:i + half_step]) / half_step
              for i in range(0, half_len - half_step, half_step)],
             alpha=0.5, color='k')

    axLb.set_ylabel("Log number of reads\nper genomic position")
    axLb.set_yscale('log')
    axLb.grid()
    axLb.set_xlabel('Distance between mapping position of the two ends\n'
                    '(averaged in windows of 20 nucleotides)')

    if full_step:
        for d in range(4):
            axRp.plot([sum(dirs[d,i:i + full_step]) / (
                sum(sum_dirs[i:i + full_step]) + 0.1)
                       for i in range(half_len, full_len + full_step, full_step)],
                      alpha=0.7, label=names[d])

        axRp.spines['left'].set_visible(False)
        axRp.set_xticks(list(range(0, (full_len - half_len) // full_step + 1, 20)))
        axRp.set_xticklabels([int(i) for i in range(
            half_len, full_len + full_step, full_step * 20)])
        plt.setp(axRp.get_xticklabels(), visible=False)
        axRp.legend(title='Strand on which each read-end is mapped\n(first read-end is always smaller than second)')
        axRp.yaxis.tick_right()
        axRp.tick_params(labelleft=False)
        axRp.tick_params(labelright=False)
        axRp.set_xlim(0, full_len / full_step - half_len / full_step)
        axRp.grid()

        axRb.bar(list(range(0, full_len // full_step - half_len // full_step + 1)),
                 [sum(sum_dirs[i:i + full_step]) // full_step
                  for i in range(half_len, full_len + full_step, full_step)],
                 alpha=0.5, color='k')

        axRb.set_ylim(0.01, max(sum_dirs) * 1.1)

        axRb.spines['left'].set_visible(False)
        axRb.yaxis.tick_right()
        axRb.tick_params(labelleft=False)
        axRb.tick_params(labelright=False)
        axRb.set_xlabel('Distance between mapping position of the two ends\n'
                        '(averaged in windows of 500 nucleotide)')
        axRb.set_yscale('log')
        axRb.grid()

        # decorate...
        d = .015  # how big to make the diagonal lines in axes coordinates
        # arguments to pass to plot, just so we don't keep repeating them
        kwargs = dict(transform=axLp.transAxes, color='k', clip_on=False)
        axLp.plot((1 - d, 1 + d), (1-d, 1+d), **kwargs)  # top-left diagonal
        axLp.plot((1 - d, 1 + d), (-d, +d), **kwargs)  # top-right diagonal

        kwargs.update(transform=axRp.transAxes)  # switch to the bottom axes
        axRp.plot((-d, +d), (1 - d, 1 + d), **kwargs)  # bottom-left diagonal
        axRp.plot((-d, +d), (-d, +d), **kwargs)  # bottom-right diagonal

        w = .015
        h = .030
        # arguments to pass to plot, just so we don't keep repeating them
        kwargs = dict(transform=axLb.transAxes, color='k', clip_on=False)
        axLb.plot((1 - w, 1 + w), (1 - h, 1 + h), **kwargs)  # top-left diagonal
        axLb.plot((1 - w, 1 + w), (  - h,   + h), **kwargs)  # top-right diagonal

        kwargs.update(transform=axRb.transAxes)  # switch to the bottom axes
        axRb.plot((- w, + w), (1 - h, 1 + h), **kwargs)  # bottom-left diagonal
        axRb.plot((- w, + w), (  - h,   + h), **kwargs)  # bottom-right diagonal

        plt.subplots_adjust(wspace=0.05)
        plt.subplots_adjust(hspace=0.1)
    else:
        axLp.legend(title='Strand on which each read-end is mapped\n(first read-end is always smaller than second)')

    if savefig:
        tadbit_savefig(savefig)


# For back compatibility
def insert_sizes(fnam, savefig=None, nreads=None, max_size=99.9, axe=None,
                 show=False, xlog=False, stats=('median', 'perc_max'),
                 too_large=10_000):
    """
    Deprecated function, use fragment_size
    """
    warn("WARNING: function has been replaced by fragment_size", category=DeprecationWarning,)
    return fragment_size(fnam, savefig=savefig, nreads=nreads, max_size=max_size, axe=axe,
                         show=show, xlog=xlog, stats=stats,
                         too_large=too_large)
