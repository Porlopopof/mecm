# -*- coding: utf-8 -*-
# Author: Quentin Baghi 2017
# This code provides routines for PSD estimation using a peace-continuous model
# that assumes that the logarithm of the PSD is linear per peaces.
import copy
import numpy as np
# FTT modules
import pyfftw
from scipy import interpolate
from scipy import linalg as la
from scipy import optimize
from pyfftw.interfaces.numpy_fft import fft, ifft

pyfftw.interfaces.cache.enable()


def least_squares(mat, y):

    ata = mat.conjugate().transpose().dot(mat)

    return la.pinv(ata).dot(mat.conjugate().transpose().dot(y))


# ==============================================================================
# General PSD CLASS
# ==============================================================================
class PSD(object):

    def __init__(self, n_data, fs, fmin=None, fmax=None):

        # Sampling frequency
        self.fs = fs
        # Size of the sample
        self.n_data = n_data
        self.f = np.fft.fftfreq(n_data) * fs
        self.n = np.int((n_data - 1) / 2.)

        if fmin is None:
            self.fmin = fs / n_data
        else:
            self.fmin = fmin
        if fmax is None:
            self.fmax = fs / 2
        else:
            self.fmax = fmax

        # Flexible interpolation of the estimated PSD
        self.log_psd_fn = None

    def periodogram(self, y_fft, K2=None):
        """
        Simple periodogram with no windowing
        """
        if K2 is None:
            per = np.abs(y_fft)**2/len(y_fft)
        else:
            per = np.abs(y_fft)**2/K2

        return per

    def psd_fn(self, x):
        return np.exp(self.log_psd_fn(np.log(x)))

    def calculate(self, arg):
        """
        Calculate the spectrum = PSD * fs / 2 at frequencies x

        """

        if (type(arg) == np.int) | (type(arg) == np.int64):
            n_data = arg
            # Symmetrize the estimates
            if n_data % 2 == 0:  # if n_data is even
                # Compute PSD from f=0 to f = fs/2
                if n_data == self.n_data:
                    n = self.n
                    f_tot = np.abs(np.concatenate(([self.f[1]],
                                                   self.f[1:n+2])))
                else:
                    f = np.fft.fftfreq(n_data) * self.fs
                    n = np.int((n_data - 1) / 2.)
                    f_tot = np.abs(np.concatenate(([f[1]], f[1:n+2])))

                spectr = self.psd_fn(f_tot)
                spectr_sym = np.concatenate((spectr[0:n+1],
                                             spectr[1:n+2][::-1]))

            else:  # if n_data is odd
                if n_data == self.n_data:
                    n = self.n
                    f_tot = np.abs(np.concatenate(([self.f[1]],
                                                   self.f[1:n+1])))
                else:
                    f = np.fft.fftfreq(n_data) * self.fs
                    n = np.int((n_data - 1) / 2.)
                    f_tot = np.abs(np.concatenate(([f[1]], f[1:n+1])))

                spectr = self.psd_fn(f_tot)
                spectr_sym = np.concatenate((spectr[0:n+1],
                                             spectr[1:n+1][::-1]))

        elif type(arg) == np.ndarray:

            f = arg[:]
            spectr_sym = self.psd_fn(f)

        else:

            raise TypeError("Argument must be integer or ndarray")

        return spectr_sym

    def calculate_autocorr(self, n_data):
        """
        Compute the autocovariance function from the PSD.

        """

        return np.real(ifft(self.calculate(2*n_data))[0:n_data])


# ==============================================================================
# Spline PSD model
# ==============================================================================
class PSDSpline(PSD):

    def __init__(self, n_data, fs, n_knots=30, d=3, fmin=None, fmax=None,
                 f_knots=None, ext=3):

        PSD.__init__(self, n_data, fs, fmin=fmin, fmax=fmax)

        # Number of knots for the log-PSD spline model
        self.n_knots = n_knots
        # Create a dictionary corresponding to each data length
        self.logf = {n_data: np.log(self.f[1:self.n+1])}
        # Set the knot grid
        if f_knots is None:
            self.f_knots = self.choose_knots()
            self.f_min_est = self.f[1]
            self.f_max_est = self.f[self.n]
        else:
            self.f_knots = f_knots
            self.n_knots = len(self.f_knots)

            self.f_min_est = copy.deepcopy(self.fmin)
            self.f_max_est = copy.deepcopy(self.fmax)

        self.logf_knots = np.log(self.f_knots)
        # Spline order
        self.d = d
        self.C0 = -0.57721
        # Spline coefficient vector
        self.beta = []
        # PSD at positive Fourier frequencies
        self.logS = []
        # Control frequencies
        self.logfc = np.concatenate((np.log(self.f_knots),
                                     [np.log(self.fs/2)]))
        self.logSc = []
        # Spline extension
        self.ext = ext

    def set_knots(self, f_knots):

        self.f_knots = f_knots
        self.logf_knots = np.log(self.f_knots)
        self.logfc = np.concatenate((np.log(self.f_knots),
                                     [np.log(self.fs / 2)]))

    def target_func(self, x, n0, ns):

        return n0 - (1-x**(self.n_knots))/(1-x) - ns

    def choose_knots(self):
        """

        Choose frequency knots such that

        f_knots = 10^-n_knots

        where the difference
        n_knots[j+1] - n_knots[j] = dn[j]

        is a geometric series.

        Parameters
        ----------
        n_knots : scalar integer
            number of knots
        fmin : scalar float
            minimum frequency knot
        fmax : scalar float
            maximum frequency knot


        """

        base = 10
        # base = np.exp(1)
        ns = - np.log(self.fmax)/np.log(base)
        n0 = - np.log(self.fmin)/np.log(base)
        jvect = np.arange(0, self.n_knots)
        alpha_guess = 0.8

        result = optimize.fsolve(lambda x: self.target_func(x, n0, ns),
                                 alpha_guess)
        alpha = result[0]
        n_knots = n0 - (1-alpha**jvect)/(1-alpha)
        f_knots = base**(-n_knots)

        # Eliminate the edges to satisfy Schoenberg-Whitney conditions
        f_knots = f_knots[(f_knots > self.fmin) & (f_knots < self.fmax)]

        return np.sort(f_knots)

    def estimate(self, y, wind='hanning'):
        """

        Estimate the log-PSD using spline model by least-square method

        Parameters
        ----------
        y : array_like
            data (typically model residuals) in the time domain


        """

        if type(wind) == np.ndarray:
            w = wind[:]
        elif wind == 'hanning':
            w = np.hanning(len(y))
        per = np.abs(fft(y * w)) ** 2 / np.sum(w ** 2)

        # Compute the spline parameter vector for the log-PSD model
        self.estimate_from_periodogram(per)

    def estimate_from_freq(self, y_fft, k2=None):
        """

        Estimate the log-PSD using spline model by least-square method from the
        discrete Fourier transformed data. This function is useful to avoid
        to compute FFTs multiple times.


        """

        # If there is only one periodogram
        if type(y_fft) == np.ndarray:
            per = self.periodogram(y_fft, K2=k2)
        # Otherwise calculate the periodogram for each data set:
        elif type(y_fft) == list:
            per = [self.periodogram(y_fft[i], K2=k2[i])
                   for i in range(len(y_fft))]

        self.estimate_from_periodogram(per)

    def estimate_from_periodogram(self, per):
        """

        Estimate PSD from the periodogram

        """

        # If there is only one periodogram
        if type(per) == np.ndarray:
            self.log_psd_fn = self.spline_lsqr(per)
            self.beta = self.log_psd_fn.get_coeffs()
        elif type(per) == list:
            # If there are several periodograms, average the estimates
            spl_list = [self.spline_lsqr(I0)
                        for I0 in per if self.fs / len(I0) < self.f_knots[0]]
            self.beta = sum([spl.get_coeffs for spl in spl_list])/len(per)
            self.log_psd_fn = interpolate.BSpline(spl_list[0].get_knots(),
                                                  self.beta, self.d)

        # Estimate psd at positive Fourier log-frequencies
        self.logS = self.log_psd_fn(self.logf[self.n_data])

        # Update PSD control values (for Bayesian estimation)
        self.logSc = self.log_psd_fn(self.logfc)

    def spline_lsqr(self, per):
        """

        Fit a spline to the log periodogram using least-squares

        Parameters
        ----------
        per : ndarray
            periodogram
        ext : extint or str, optional
            Controls the extrapolation mode for elements not in the interval
            defined by the knot sequence.
                if ext=0 or ‘extrapolate’, return the extrapolated value.
                if ext=1 or ‘zeros’, return 0
                if ext=2 or ‘raise’, raise a ValueError
                if ext=3 of ‘const’, return the boundary value
            The default value is 3.


        """

        NI = len(per)

        if NI not in list(self.logf.keys()):
            f = np.fft.fftfreq(NI)*self.fs
            self.logf[NI] = np.log(f[f > 0])
        else:
            f = np.concatenate(([0], np.exp(self.logf[NI])))

        n = np.int((NI-1)/2.)
        z = per[1:n + 1]
        v = np.log(z) - self.C0

        # Spline estimator of the log-PSD
        inds_est = np.where((self.f_min_est <= f[1:self.n + 1])
                            & (f[1:self.n + 1] <= self.f_max_est))[0]
        spl = interpolate.LSQUnivariateSpline(self.logf[NI][inds_est],
                                              v[inds_est],
                                              self.logf_knots,
                                              k=self.d,
                                              ext=self.ext)

        return spl
