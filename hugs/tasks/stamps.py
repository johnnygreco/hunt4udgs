from __future__ import division, print_function
                      

import os
import numpy as np
import matplotlib.pyplot as plt
from astropy.table import Table, vstack, hstack

from .sersic_fit import sersic_fit
from .. import utils
from ..datasets import hsc
from .. import imfit

__all__ = ['get_candy_stamps', 'fit_candy', 'run_batch_fit']


def get_candy_stamps(cat, label=None, bands='GRI', 
                     outdir=None, obj_type='candy', **kwargs):
    """
    Get postage stamps from database. 

    Parameters
    ----------
    cat : astropy.table.Table
        Source catalog (output from hugs_pipe).
    label : string, optional
        Label for stamps. If None, will use time.
    bands : string or list, optional
        Photometric bands to get. 
    outdir : string, optional
        Output directory.
    """
    
    if label is None:
        import time
        label = time.strftime("%Y%m%d-%H%M%S")
        rundir = os.path.join(outdir, 'stamps_'+label)
    else:
        rundir = os.path.join(outdir, label)
    utils.mkdir_if_needed(rundir)

    if outdir is None:
        outdir = os.path.join(utils.io, 'stamps')

    new_cat_fn = os.path.join(rundir, 'candy.csv')
    cat.write(new_cat_fn)

    coordlist_fn = os.path.join(rundir, 'coordlist.txt')
    hsc.make_query_coordlist(cat, coordlist_fn, bands, **kwargs)
    hsc.cutout_query(coordlist_fn, outdir=rundir, **kwargs)

    # give stamps more useful names
    stamp_files = [f for f in os.listdir(rundir) if f[-4:]=='fits']
    stamp_files = sorted(stamp_files, key=lambda f: int(f.split('-')[0]))
    grouped_files = utils.grouper(stamp_files, len(bands))

    for num, files in enumerate(grouped_files):
        for i in range(len(bands)):
            old_fn = files[i]
            rerun = old_fn.split('-')[-1]
            rerun = rerun.replace('_', '-')
            new_fn = obj_type+'-{}-{}-{}'.format(num, bands[i].lower(), rerun)
            old_fn = os.path.join(rundir, old_fn)
            new_fn = os.path.join(rundir, new_fn)
            os.rename(old_fn, new_fn)


def fit_candy(num, indir, outdir, init_params={}, save_figs=True,
              mask_kwargs={}):
    """
    Fit single candidate.

    Notes
    -----
    All bands are fit separately. Then, the band with the smallest
    fractional error in r_eff is used as a reference for forced 
    photometry on the other bands, where the position and sercic
    index is held fixed. 
    """
    import lsst.afw.image 
    import lsst.afw.geom 
    plt.style.use('jpg')

    files = [f for f in os.listdir(indir) if 
             f.split('-')[-1]=='wide.fits' and int(f.split('-')[1])==num]

    if save_figs:
        fig, axes = plt.subplots(len(files), 3, figsize=(15,15))
        fig.subplots_adjust(wspace=0.05, hspace=0.05)

    # fit all bands separately
    r_e_err = []
    fits = []
    mask_files = [] 
    for fn in files:
        band = fn.split('-')[2]
        fn = os.path.join(indir, fn)
        prefix = os.path.join(outdir, 'candy-{}-{}'.format(num, band))
        sersic = sersic_fit(fn, 
                            prefix=prefix,
                            init_params=init_params,
                            visualize=False, 
                            band=band, 
                            clean='config', 
                            mask_kwargs=mask_kwargs)
        r_e_err.append(sersic.r_e_err/sersic.r_e)
        fits.append(sersic)
        mask_files.append(prefix+'_photo_mask.fits')
    r_e_err = np.array(r_e_err)
    best_idx = r_e_err.argmin()
    best_band = files[best_idx].split('-')[2]

    best = fits[best_idx]

    # get wcs for best fit object
    best_fn = os.path.join(indir, files[best_idx])
    header = lsst.afw.image.readMetadata(best_fn)
    wcs = lsst.afw.image.makeWcs(header)
    X0_hsc, Y0_hsc = header.get('CRVAL1A'), header.get('CRVAL2A')
    coord = wcs.pixelToSky(best.X0+X0_hsc, best.Y0+Y0_hsc)
    ra, dec = coord.getPosition(lsst.afw.geom.degrees)

    # generate ouput columns for best band
    dX0 = best.X0 - header.get('NAXIS1')/2
    dY0 = best.Y0 - header.get('NAXIS2')/2
    data = [num, best_band, ra, dec, best.n, best.m_tot, best.mu_0, 
            best.ell, best.r_e*utils.pixscale, best.PA, dX0, dY0]
    names = ['candy_num', 
             'best_band',
             'ra',
             'dec',
             'n', 
             'm_tot('+best_band+')', 
             'mu_0('+best_band+')',
             'ell('+best_band+')',
             'r_e('+best_band+')', 
             'PA('+best_band+')',
             'dX0', 
             'dY0']
    results = Table(rows=[data], names=names)
    
    if save_figs:
        imfit.viz.img_mod_res(os.path.join(indir, files[best_idx]), 
                              fits[best_idx].params, 
                              mask_files[best_idx], 
                              band=best_band,
                              subplots=(fig, axes[0]),
                              show=False)
    
    # perform forced photometry with "best" band as the reference
    ax_count = 1
    for idx, fn in enumerate(files):
        if idx!=best_idx:
            band = fn.split('-')[2]
            fn = os.path.join(indir, fn)
            init_params = {
                'X0': [fits[best_idx].X0, 'fixed'],
                'Y0': [fits[best_idx].Y0, 'fixed'],
                'n': [fits[best_idx].n, 'fixed'],
                'PA': [fits[best_idx].PA, 'fixed'],
                'ell': [fits[best_idx].ell, 'fixed'],
                'r_e': fits[best_idx].r_e,
                'I_e': fits[idx].I_e
                }
            prefix = 'candy-{}-{}-forced-{}'.format(num, band, best_band)
            prefix = os.path.join(outdir, prefix)
            sersic = sersic_fit(fn, 
                             prefix=prefix,
                             init_params=init_params,
                             visualize=False, 
                             clean='config',
                             band=band,
                             photo_mask_fn=mask_files[best_idx])

            # generate output columns for other bands
            data = [sersic.m_tot, sersic.mu_0, sersic.ell,
                    sersic.r_e*utils.pixscale, sersic.PA]
            names = ['m_tot('+band+')', 'mu_0('+band+')', 'ell('+band+')',
                     'r_e('+band+')', 'PA('+band+')']
            temp = Table(rows=[data], names=names)
            results = hstack([results, temp])

            if save_figs:
                imfit.viz.img_mod_res(fn, 
                                      sersic.params, 
                                      mask_files[best_idx], 
                                      band=band,
                                      subplots=(fig, axes[ax_count]),
                                      show=False, 
                                      titles=False)
                axes[ax_count]
                ax_count += 1

    for mask_fn in mask_files:
        os.remove(mask_fn)

    if save_figs:
        fig_fn = 'candy-{}-fit-results.pdf'.format(num)
        fig_fn = os.path.join(outdir, fig_fn)
        fig.savefig(fig_fn)
        plt.close('all')

    return results


def run_batch_fit(rundir, bands='GRI', save_figs=True):
    """
    Fit Seric models to postage-stamp candidate images.
    
    Parameters
    ----------
    rundir : string
        Path to fits files.
    bands : string or list, optional
        Photometric bands to be fit. 
    save_figs : bool
        If True, save a summary figure for each candidate.

    """
    cat_fn = os.path.join(rundir, 'candy.csv')
    cat = Table.read(cat_fn)

    # get number of candidates
    stamp_files = [f for f in os.listdir(rundir) if 
                   f.split('-')[-1]=='wide.fits']
    assert len(stamp_files)%len(bands)==0
    num_candy = len(stamp_files)//len(bands)

    # all imfit results will be saved in imfit directory
    imfitdir = os.path.join(rundir, 'imfit')
    utils.mkdir_if_needed(imfitdir)

    # loop over candidates 
    candy_params = Table()
    for num in range(num_candy):	
        # get initial guess parameters
        pa = cat['orientation'][num] * 180.0/np.pi
        pa = 90 + pa 
        ell = cat['ellipticity'][num]
        init_params = {'PA': [pa, 0, 180],
                       'ell': [ell, 0, 0.999]}
        results = fit_candy(
            num, rundir, imfitdir, init_params, save_figs)
        candy_params = vstack([candy_params, results])

    out_fn = os.path.join(imfitdir, 'candy-imfit-params.csv')
    candy_params.write(out_fn)
