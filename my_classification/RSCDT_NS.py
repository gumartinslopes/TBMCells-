# -*- coding: utf-8 -*-
"""
Created on Tue Jan 17 14:41:20 2023

@author: Naqib Sad Pathan

Reference

Gong, L., Li, S., Pathan, N. S., Rohde, G. K., Rubaiyat, A. H. M., & Thareja, S. (2023). 
"The Radon Signed Cumulative Distribution Transform and its applications in classification of Signed Images."
arXiv preprint arXiv:2307.15339.
"""

import numpy as np
import numpy.linalg as LA
import multiprocessing as mp

from pytranskit.optrans.continuous.radonscdt import RadonSCDT

eps = 1e-6
x0_range = [0, 1]
x_range = [0, 1]
Rdown = 1  # downsample radon projections (w.r.t. angles)
theta = np.linspace(0, 176, 45// Rdown)

class RSCDT_NS:
    def __init__(self, num_classes, thetas=theta, rm_edge=False):
        """
        Parameters
        ----------
        num_classes : integer, total number of classes
        thetas : array-like, angles in degrees for taking radon projections
            default = [0,180) with increment of 4 degrees.
        rm_edge : boolean flag; IF TRUE the first and last points of RSCDTs will be removed
            default = False
        """
        self.num_classes = num_classes
        self.thetas = thetas
        self.rm_edge = rm_edge
        self.subspaces = []
        self.len_subspace = 0

    def fit(self, Xtrain, Ytrain, no_deform_model=True):
        """Fit linear model.
        
        Parameters
        ----------
        Xtrain : array-like, shape (n_samples, n_rows, n_columns)
            Image data for training.
        Ytrain : ndarray of shape (n_samples,)
            Labels of the training images.
        no_deform_model : boolean flag; IF TRUE, no deformation model will be added
            default = False.
        """
        
        # calculate the RSCDT using parallel CPUs
        print('\nCalculating RSCDTs for training images ...')
        Xrscdt = self.rscdt_parallel(Xtrain)
        # generate the basis vectors for each class
        print('Generating basis vectors for each class ...')
        for class_idx in range(self.num_classes):
            class_data = Xrscdt[Ytrain == class_idx]
            if no_deform_model:
                flat = class_data.reshape(class_data.shape[0], -1)
            else:
                class_data_trans = self.add_trans_samples(class_data)
                flat = class_data_trans.reshape(class_data_trans.shape[0], -1)
            u, s, vh = LA.svd(flat,full_matrices=False)

            cum_s = np.cumsum(s)
            cum_s = cum_s/np.max(cum_s)

            max_basis = (np.where(cum_s>=0.99)[0])[0] + 1
            
            if max_basis > self.len_subspace:
                self.len_subspace = max_basis
            
            basis = vh[:flat.shape[0]]
            self.subspaces.append(basis)


    def predict(self, Xtest, use_gpu=False):
        """Predict using the linear model
        
        Let :math:`B^k` be the basis vectors of class :math:`k`, and :math:`x` be the RSCDT sapce feature vector of an input, 
        the NS method performs classification by
        
        .. math::
            arg\min_k \| B^k (B^k)^T x - x\|^2
        
        Parameters
        ----------
        Xtest : array-like, shape (n_samples, n_rows, n_columns)
            Image data for testing.
        use_gpu: boolean flag; IF TRUE, use gpu for calculations
            default = False.
            
        Returns
        -------
        ndarray of shape (n_samples,)
           Predicted target values per element in Xtest.
           
        """
        
        # calculate the RSCDT using parallel CPUs
        print('\nCalculating RSCDTs for testing images ...')
        Xrscdt = self.rscdt_parallel(Xtest)
        
        # vectorize RSCDT matrix
        X = Xrscdt.reshape([Xrscdt.shape[0], -1])
        
        # import cupy for using GPU
        if use_gpu:
            import cupy as cp
            X = cp.array(X)
        
        # find nearest subspace for each test sample
        print('Finding nearest subspace for each test sample ...')
        D = []
        for class_idx in range(self.num_classes):
            basis = self.subspaces[class_idx]
            basis = basis[:self.len_subspace,:]
            
            if use_gpu:
                D.append(cp.linalg.norm(cp.matmul(cp.matmul(X, cp.array(basis).T), 
                                                  cp.array(basis)) -X, axis=1))
            else:
                proj = X @ basis.T  # (n_samples, n_basis)
                projR = proj @ basis  # (n_samples, n_features)
                D.append(LA.norm(projR - X, axis=1))
        if use_gpu:
            preds = cp.argmin(cp.stack(D, axis=0), axis=0)
            return cp.asnumpy(preds)
        else:
            D = np.stack(D, axis=0)
            preds = np.argmin(D, axis=0)
            return preds


    def fun_rscdt_single(self, I0):
        # I: (rows, columns)
        #radonscdt = RadonSCDT(self.thetas)
        #Ihat,mpos,mneg= radonscdt.forward(I0)
        x0_range=[0,1]
        x_range=[0,1]
        template=np.ones_like(I0)
        RSCDT=RadonSCDT()
        Ihat,ref,mpos_all,mneg_all,rad1=RSCDT.forward( x0_range, template, x_range, I0, rm_edge=False)
        return Ihat
    
    def fun_rscdt_batch(self, data):
        # data: (n_samples, rows, columns)
        dataRSCDT = [self.fun_rscdt_single(data[j, :, :] + eps) for j in range(data.shape[0])]
        return np.array(dataRSCDT)
    
    def rscdt_parallel(self, X):
        rscdt_features = self.fun_rscdt_batch(X)
        return rscdt_features
        
    def add_trans_samples(self, rscdt_features):
        # rscdt_features: (n_samples, proj_len, num_angles)
        # deformation vectors for  translation
        v1, v2 = np.cos(self.thetas*np.pi/180), np.sin(self.thetas*np.pi/180)
        v1 = np.repeat(v1[np.newaxis], rscdt_features.shape[1], axis=0)
        v2 = np.repeat(v2[np.newaxis], rscdt_features.shape[1], axis=0)
        return np.concatenate([rscdt_features, v1[np.newaxis], v2[np.newaxis]])
