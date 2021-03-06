from __future__ import division
from mathfunc import det_dim_2, det_dim_3, inv, inv_dim_3, cross_dim_2, transpose_dim_3, dot_mat_dim_3, EV, Eigensystem, dot_const_mat_dim_3
import numpy as np
import math
from math import sqrt
from numba import jit, njit, prange

# Calculate elastic forces
@njit(parallel=True)
def tetraElasticity(At, A0, Ft, G, K, k, mu, tets, Vn, Vn0, ne, eps):

  # Deformed volume
  #vol = det(At)/6.0

  # Apply growth to reference state
  Ar = np.zeros((ne,3,3), dtype=np.float64)
  Ar[:] = dot_mat_dim_3(G[:], A0[:])
  #Ar[:] = dot_const_mat_dim_3(G, A0[:])
  #Ar = np.dot(At, G)
  #Ar = G*np.array(A0)

  # Calculate deformation gradient
  F = np.zeros((ne,3,3), dtype=np.float64)
  F[:] = dot_mat_dim_3(At[:], inv_dim_3(Ar[:]))   # Ar: rest tetra, At: material tetra

  # Calculate left Cauchy-Green strain tensor
  B = np.zeros((ne,3,3), dtype=np.float64)
  B[:] = dot_mat_dim_3(F[:], transpose_dim_3(F[:]))

  # Calculate relative volume change and averaged nodal volume change
  J = np.zeros(ne, dtype=np.float64)
  J1 = np.zeros(ne, dtype=np.float64)
  J2 = np.zeros(ne, dtype=np.float64)
  J3 = np.zeros(ne, dtype=np.float64)
  J4 = np.zeros(ne, dtype=np.float64)
  Ja = np.zeros(ne, dtype=np.float64)
  J[:] = det_dim_3(F[:]) # Relative volume change
  J1[:] = Vn[tets[:,0]]/Vn0[tets[:,0]]
  J2[:] = Vn[tets[:,1]]/Vn0[tets[:,1]]
  J3[:] = Vn[tets[:,2]]/Vn0[tets[:,2]]
  J4[:] = Vn[tets[:,3]]/Vn0[tets[:,3]]
  Ja[:] = (J1[:] + J2[:] + J3[:] + J4[:])/4.0   # Averaged nodal volume change

  # Decide if need for SVD or not
  for i in prange(ne):

    ll1, ll2, ll3 = EV(B[i])

    if ll3 >= eps**2 and J[i] > 0.0: # No need for SVD

     # Calculate the total stress (shear stress + bulk stress)
      powJ23 = np.power(J[i], 2.0/3.0)
      S = (B[i] - np.identity(3)*np.trace(B[i])/3.0)*mu[i]/(J[i]*powJ23) + np.identity(3)*K*(Ja[i]-1.0)
      P = np.dot(S, inv(F[i].transpose()))*J[i]
      W = 0.5*mu[i]*(np.trace(B[i])/powJ23 - 3.0) + 0.5*K*((J1[i]-1.0)*(J1[i]-1.0) + (J2[i]-1.0)*(J2[i]-1.0) + (J3[i]-1.0)*(J3[i]-1.0) + (J4[i]-1.0)*(J4[i]-1.0))*0.25

    else:  # Needs SVD

      C = np.dot(F[i].transpose(), F[i])

      V = np.identity(3)
      eva = [0.0]*3
      w2, v2 = Eigensystem(3, C, V, eva)
      #u2, w2, v2 = np.linalg.svd(C, full_matrices=True)
      #w2, v2 = np.linalg.eig(C)

      l1 = sqrt(w2[0])
      l2 = sqrt(w2[1])
      l3 = sqrt(w2[2])

      if det_dim_2(v2) < 0.0:
        v2[0,0] = -v2[0,0]
        v2[1,0] = -v2[1,0]
        v2[2,0] = -v2[2,0]
      #v2 = np.transpose(v2)

      Fdi = np.identity(3)
      if l1 >= 1e-25:
        Fdi[0,0] = 1.0/l1
        Fdi[1,1] = 1.0/l2
        Fdi[2,2] = 1.0/l3

      U = np.dot(F[i], np.dot(v2, Fdi))

      if l1 < 1e-25:
        U[0,0] = U[1,1]*U[2,2] - U[2,1]*U[1,2]
        U[1,0] = U[2,1]*U[0,2] - U[0,1]*U[2,2]
        U[2,0] = U[0,1]*U[1,2] - U[1,1]*U[0,2]

      if det_dim_2(F[i]) < 0.0:
        l1 = -l1
        U[0,0] = -U[0,0]
        U[1,0] = -U[1,0]
        U[2,0] = -U[2,0]

      Pd = np.identity(3)
      pow23 = np.power(eps*l2*l3, 2.0/3.0)
      Pd[0,0] = mu[i]/3.0*(2.0*eps - l2*l2/eps - l3*l3/eps)/pow23 + k*(l1-eps) + K*(Ja[i]-1.0)*l2*l3
      Pd[1,1] = mu[i]/3.0*(-eps*eps/l2 + 2.0*l2 - l3*l3/l2)/pow23 + mu[i]/9.0*(-4.0*eps/l2 - 4.0/eps*l2 + 2.0/eps/l2*l3*l3)/pow23*(l1-eps) + K*(Ja[i]-1.0)*l1*l3
      Pd[2,2] = mu[i]/3.0*(-eps*eps/l3 - l2*l2/l3 + 2.0*l3)/pow23 + mu[i]/9.0*(-4.0*eps/l3 + 2.0/eps*l2*l2/l3 - 4.0/eps*l3)/pow23*(l1-eps) + K*(Ja[i]-1.0)*l1*l2
      P = np.dot(U, np.dot(Pd, v2.transpose()))
      W = 0.5*mu[i]*((eps*eps + l2*l2 + l3*l3)/pow23 - 3.0) + mu[i]/3.0*(2.0*eps - l2*l2/eps - l3*l3/eps)/pow23*(l1-eps) + 0.5*k*(l1-eps)*(l1-eps) + 0.5*K*((J1[i]-1.0)*(J1[i]-1.0) + (J2[i]-1.0)*(J2[i]-1.0) + (J3[i]-1.0)*(J3[i]-1.0) + (J4[i]-1.0)*(J4[i]-1.0))/4.0

  # Increment total elastic energy
  #if J*J > 1e-50:
    #Ue += W*vol/J

    # Calculate tetra face negative normals (because traction Ft=-P*n)
    xr1 = np.array([Ar[i,0,0], Ar[i,1,0], Ar[i,2,0]])
    xr2 = np.array([Ar[i,0,1], Ar[i,1,1], Ar[i,2,1]])
    xr3 = np.array([Ar[i,0,2], Ar[i,1,2], Ar[i,2,2]])
    N1 = cross_dim_2(xr3, xr1)
    N2 = cross_dim_2(xr2, xr3)
    N3 = cross_dim_2(xr1, xr2)
    N4 = cross_dim_2(xr2-xr3, xr1-xr3)

    # Distribute forces among tetra vertices
    #Ft[tets[i][0]] += np.array((np.dot(np.array(P), (N1 + N2 + N3)[np.newaxis].T).T/6.0).ravel(), dtype = float)
    Ft[tets[i,0]] += np.dot(P, (N1 + N2 + N3).T)/6.0
    Ft[tets[i,1]] += np.dot(P, (N1 + N3 + N4).T)/6.0
    Ft[tets[i,2]] += np.dot(P, (N2 + N3 + N4).T)/6.0
    Ft[tets[i,3]] += np.dot(P, (N1 + N2 + N4).T)/6.0
  #Ft[tets[i][0]] += (np.dot(np.array(P), (N1 + N2 + N3)[np.newaxis].T).T/6.0).ravel()
  #Ft[tets[i][1]] += (np.dot(np.array(P), (N1 + N3 + N4)[np.newaxis].T).T/6.0).ravel()
  #Ft[tets[i][2]] += (np.dot(np.array(P), (N2 + N3 + N4)[np.newaxis].T).T/6.0).ravel()
  #Ft[tets[i][3]] += (np.dot(np.array(P), (N1 + N2 + N4)[np.newaxis].T).T/6.0).ravel()

  return Ft

# Newton dynamics (Integrate velocity into displacement)
@njit(parallel=True)
def move(nn, Ft, Vt, Ut, gamma, Vn0, rho, dt):
  for i in prange(nn):
    Ft[i] -= Vt[i]*gamma*Vn0[i]
    Vt[i] += Ft[i]/(Vn0[i]*rho)*dt
  Ut[:] += Vt[:]*dt
  Ft[:] = np.zeros((nn,3), dtype = np.float64)

  return Ft, Ut, Vt
