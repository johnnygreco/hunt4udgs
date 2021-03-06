from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import numpy as np

__all__ = ['rmedian']

def _ring(r_inner, r_outer, dtype=np.int, invert=False):
    """
    Generate a 2D ring footprint.

    Paramters
    ---------
    r_inner : int
        The inner radius of ring in pixels.
    r_outer : int
        The outer radius of ring in pixels.
    dtype : data type, optional
        The data type of the output array
    invert : bool, optional
        If True, invert the ring kernal (i.e., 1 <--> 0).

    Returns
    -------
    fp : 2D ndarray
        The ring footprint with 1's in the 
        annulus and 0's everywhere else.
    """
    assert r_outer >= r_inner, 'must have r_outer >= r_inner'
    x = np.arange(-int(r_outer), int(r_outer)+1)
    r = np.sqrt(x**2 + x[:,None]**2)
    annulus = (r>r_inner) & (r<=r_outer)
    if invert:
        annulus = ~annulus
    r[annulus] = 1
    r[~annulus] = 0
    fp = r.astype(dtype)
    return fp


def rmedian(data, r_inner, r_outer, **kwargs):
    """
    Median filter image with a ring footprint. This
    function produces results similar to the IRAF 
    task of the same name (except this is much faster). 

    Parameters
    ----------
    data : ndarray
        Input image array 
    r_inner : int
        The inner radius of the ring in pixels.
    r_outer : int
        The outer radius of the ring in pixels.
    """
    from scipy.ndimage import median_filter

    fp = _ring(r_inner, r_outer, **kwargs)
    filtered_data = median_filter(data, footprint=fp)
    return filtered_data
