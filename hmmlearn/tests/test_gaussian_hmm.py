from __future__ import absolute_import

from unittest import TestCase

import numpy as np
import pytest

from hmmlearn import hmm
from hmmlearn.utils import normalize

from ._test_common import fit_hmm_and_monitor_log_likelihood, make_covar_matrix


class GaussianHMMTestMixin(object):
    covariance_type = None  # set by subclasses

    def setUp(self):
        self.prng = prng = np.random.RandomState(10)
        self.n_components = n_components = 3
        self.n_features = n_features = 3
        self.startprob = prng.rand(n_components)
        self.startprob = self.startprob / self.startprob.sum()
        self.transmat = prng.rand(n_components, n_components)
        self.transmat /= np.tile(self.transmat.sum(axis=1)[:, np.newaxis],
                                 (1, n_components))
        self.means = prng.randint(-20, 20, (n_components, n_features))
        self.covars = dict(
            (cv_type, make_covar_matrix(cv_type, n_components, n_features))
            for cv_type in ["spherical", "tied", "diag", "full"])
        self.expanded_covars = {
            'spherical': [np.eye(n_features) * cov
                          for cov in self.covars['spherical']],
            'diag': [np.diag(cov) for cov in self.covars['diag']],
            'tied': [self.covars['tied']] * n_components,
            'full': self.covars['full'],
        }

    def test_bad_covariance_type(self):
        with pytest.raises(ValueError):
            h = hmm.GaussianHMM(20, covariance_type='badcovariance_type')
            h.means_ = self.means
            h.covars_ = []
            h.startprob_ = self.startprob
            h.transmat_ = self.transmat
            h._check()

    def test_score_samples_and_decode(self):
        h = hmm.GaussianHMM(self.n_components, self.covariance_type,
                            init_params="st")
        h.means_ = self.means
        h.covars_ = self.covars[self.covariance_type]

        # Make sure the means are far apart so posteriors.argmax()
        # picks the actual component used to generate the observations.
        h.means_ = 20 * h.means_

        gaussidx = np.repeat(np.arange(self.n_components), 5)
        n_samples = len(gaussidx)
        X = self.prng.randn(n_samples, self.n_features) + h.means_[gaussidx]
        h._init(X)
        ll, posteriors = h.score_samples(X)

        self.assertEqual(posteriors.shape, (n_samples, self.n_components))
        assert np.allclose(posteriors.sum(axis=1), np.ones(n_samples))

        viterbi_ll, stateseq = h.decode(X)
        assert np.allclose(stateseq, gaussidx)

    def test_sample(self, n=1000):
        h = hmm.GaussianHMM(self.n_components, self.covariance_type)
        h.startprob_ = self.startprob
        h.transmat_ = self.transmat
        # Make sure the means are far apart so posteriors.argmax()
        # picks the actual component used to generate the observations.
        h.means_ = 20 * self.means
        h.covars_ = np.maximum(self.covars[self.covariance_type], 0.1)

        X, state_sequence = h.sample(n, random_state=self.prng)
        self.assertEqual(X.shape, (n, self.n_features))
        self.assertEqual(len(state_sequence), n)

    def test_fit(self, params='stmc', n_iter=5, **kwargs):
        h = hmm.GaussianHMM(self.n_components, self.covariance_type)
        h.startprob_ = self.startprob
        h.transmat_ = normalize(
            self.transmat + np.diag(self.prng.rand(self.n_components)), 1)
        h.means_ = 20 * self.means
        h.covars_ = self.covars[self.covariance_type]

        lengths = [10] * 10
        X, _state_sequence = h.sample(sum(lengths), random_state=self.prng)

        # Mess up the parameters and see if we can re-learn them.
        h.n_iter = 0
        h.fit(X, lengths=lengths)

        trainll = fit_hmm_and_monitor_log_likelihood(
            h, X, lengths=lengths, n_iter=n_iter)

        # Check that the log-likelihood is always increasing during training.
        diff = np.diff(trainll)
        message = ("Decreasing log-likelihood for {0} covariance: {1}"
                   .format(self.covariance_type, diff))
        self.assertTrue(np.all(diff >= -1e-6), message)

    def test_fit_sequences_of_different_length(self):
        lengths = [3, 4, 5]
        X = self.prng.rand(sum(lengths), self.n_features)

        h = hmm.GaussianHMM(self.n_components, self.covariance_type)
        # This shouldn't raise
        # ValueError: setting an array element with a sequence.
        h.fit(X, lengths=lengths)

    def test_fit_with_length_one_signal(self):
        lengths = [10, 8, 1]
        X = self.prng.rand(sum(lengths), self.n_features)

        h = hmm.GaussianHMM(self.n_components, self.covariance_type)
        # This shouldn't raise
        # ValueError: zero-size array to reduction operation maximum which
        #             has no identity
        h.fit(X, lengths=lengths)

    def test_fit_with_priors(self, params='stmc', n_iter=5):
        startprob_prior = 10 * self.startprob + 2.0
        transmat_prior = 10 * self.transmat + 2.0
        means_prior = self.means
        means_weight = 2.0
        covars_weight = 2.0
        if self.covariance_type in ('full', 'tied'):
            covars_weight += self.n_features
        covars_prior = self.covars[self.covariance_type]

        h = hmm.GaussianHMM(self.n_components, self.covariance_type)
        h.startprob_ = self.startprob
        h.startprob_prior = startprob_prior
        h.transmat_ = normalize(
            self.transmat + np.diag(self.prng.rand(self.n_components)), 1)
        h.transmat_prior = transmat_prior
        h.means_ = 20 * self.means
        h.means_prior = means_prior
        h.means_weight = means_weight
        h.covars_ = self.covars[self.covariance_type]
        h.covars_prior = covars_prior
        h.covars_weight = covars_weight

        lengths = [100] * 10
        X, _state_sequence = h.sample(sum(lengths), random_state=self.prng)

        # Re-initialize the parameters and check that we can converge to the
        # original parameter values.
        h_learn = hmm.GaussianHMM(self.n_components, self.covariance_type,
                                  params=params)
        h_learn.n_iter = 0
        h_learn.fit(X, lengths=lengths)

        fit_hmm_and_monitor_log_likelihood(
            h_learn, X, lengths=lengths, n_iter=n_iter)

        # Make sure we've converged to the right parameters.
        # a) means
        self.assertTrue(np.allclose(sorted(h.means_.tolist()),
                                    sorted(h_learn.means_.tolist()),
                                    0.01))
        # b) covars are hard to estimate precisely from a relatively small
        #    sample, thus the large threshold
        self.assertTrue(np.allclose(sorted(h._covars_.tolist()),
                                    sorted(h_learn._covars_.tolist()),
                                    10))


class TestGaussianHMMWithSphericalCovars(GaussianHMMTestMixin, TestCase):
    covariance_type = 'spherical'

    def test_fit_startprob_and_transmat(self):
        self.test_fit('st')


class TestGaussianHMMWithDiagonalCovars(GaussianHMMTestMixin, TestCase):
    covariance_type = 'diag'

    def test_covar_is_writeable(self):
        h = hmm.GaussianHMM(n_components=1, covariance_type="diag",
                            init_params="c")
        X = np.random.normal(size=(1000, 5))
        h._init(X)

        # np.diag returns a read-only view of the array in NumPy 1.9.X.
        # Make sure this doesn't prevent us from fitting an HMM with
        # diagonal covariance matrix. See PR#44 on GitHub for details
        # and discussion.
        assert h._covars_.flags["WRITEABLE"]

    def test_fit_left_right(self):
        transmat = np.zeros((self.n_components, self.n_components))

        # Left-to-right: each state is connected to itself and its
        # direct successor.
        for i in range(self.n_components):
            if i == self.n_components - 1:
                transmat[i, i] = 1.0
            else:
                transmat[i, i] = transmat[i, i + 1] = 0.5

        # Always start in first state
        startprob = np.zeros(self.n_components)
        startprob[0] = 1.0

        lengths = [10, 8, 1]
        X = self.prng.rand(sum(lengths), self.n_features)

        h = hmm.GaussianHMM(self.n_components, covariance_type="diag",
                            params="mct", init_params="cm")
        h.transmat_ = transmat
        h.startprob_ = startprob
        h.fit(X)

        assert np.allclose(transmat[transmat == 0.0],
                           h.transmat_[transmat == 0.0])


class TestGaussianHMMWithTiedCovars(GaussianHMMTestMixin, TestCase):
    covariance_type = 'tied'


class TestGaussianHMMWithFullCovars(GaussianHMMTestMixin, TestCase):
    covariance_type = 'full'
