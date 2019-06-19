import numpy as np
import math
from math import sqrt
from numba import jit, njit, prange
from mathfunc import dot_vec_dim_3

# Finds the nearest surface nodes to nodes (csn) and distances to them (d2s) - these are needed to set up the growth of the gray matter
@njit(parallel=True)
def dist2surf(Ut0, SN, nn, csn, d2s):
  #csn = np.zeros(nn)  # Nearest surface nodes
  #d2s = np.zeros(nn)  # Distances to nearest surface node
  for i in prange(nn):
    d2 = dot_vec_dim_3(Ut0[SN[:]] - Ut0[i], Ut0[SN[:]] - Ut0[i])
    csn[i] = np.argmin(d2)
    d2s[i] = sqrt(np.min(d2))

  return csn, d2s

# Calculate the relative growth rate
@jit
def growthRate(GROWTH_RELATIVE, t):
  #if t < 0.0:
  at = GROWTH_RELATIVE*t
    #at = GROWTH_RELATIVE + 7.4*t
  #if t >= 0.0: 
    #at = GROWTH_RELATIVE - GROWTH_RELATIVE*t

  return at

# Calculate the thickness of growing layer
@jit
def cortexThickness(THICKNESS_CORTEX, t):
  #if t < 0.0:
  H = THICKNESS_CORTEX + 0.01*t
  #if t >= 0.0:
    #H = THICKNESS_CORTEX + THICKNESS_CORTEX*t

  return H

# Calculate gray and white matter shear modulus (gm and wm) for a tetrahedron, calculate the global shear modulus
@njit(parallel=True)
def shearModulus(d2s, H, tets, ne, muw, mug, gr):
  gm = np.zeros(ne, dtype=np.float64)
  mu = np.zeros(ne, dtype=np.float64)
  for i in prange(ne):
    gm[i] = 1.0/(1.0 + math.exp(10.0*(0.25*(d2s[tets[i,0]] + d2s[tets[i,1]] + d2s[tets[i,2]] + d2s[tets[i,3]])/H - 1.0)))*0.25*(gr[tets[i,0]] + gr[tets[i,1]] + gr[tets[i,2]] + gr[tets[i,3]])
    #wm[i] = 1.0 - gm[i]
    mu[i] = muw*(1.0 - gm[i]) + mug*gm[i]  # Global modulus of white matter and gray matter

  return gm, mu

# Calculate relative (relates to d2s) tangential growth factor G
@jit
def growthTensor_tangen(Nt, gm, at, G, ne):
  A = np.zeros((ne,3,3), dtype=np.float64)
  A[:,0,0] = Nt[:,0]*Nt[:,0]
  A[:,0,1] = Nt[:,0]*Nt[:,1]
  A[:,0,2] = Nt[:,0]*Nt[:,2]
  A[:,1,0] = Nt[:,0]*Nt[:,1]
  A[:,1,1] = Nt[:,1]*Nt[:,1]
  A[:,1,2] = Nt[:,1]*Nt[:,2]
  A[:,2,0] = Nt[:,0]*Nt[:,2]
  A[:,2,1] = Nt[:,1]*Nt[:,2]
  A[:,2,2] = Nt[:,2]*Nt[:,2]
  for i in prange(ne):
    G[i] = np.identity(3) + (np.identity(3) - A[i])*gm[i]*at
  #G[i] = np.identity(3) + (np.identity(3) - np.matrix([[Nt[0]*Nt[0], Nt[0]*Nt[1], Nt[0]*Nt[2]], [Nt[0]*Nt[1], Nt[1]*Nt[1], Nt[1]*Nt[2]], [Nt[0]*Nt[2], Nt[1]*Nt[2], Nt[2]*Nt[2]]]))*gm*at

  return G

# Calculate homogeneous growth factor G
@jit
def growthTensor_homo(G, i, GROWTH_RELATIVE, t):
  G[i] = 1.0 + GROWTH_RELATIVE*t

  return G[i]

# Calculate homogeneous growth factor G (2nd version)
@jit
def growthTensor_homo_2(G, i, GROWTH_RELATIVE):
  G[i] = GROWTH_RELATIVE

  return G[i]

# Calculate cortical layer (relates to d2s) homogeneous growth factor G
@jit
def growthTensor_relahomo(gm, G, i, GROWTH_RELATIVE, t):
  #G[i] = np.full((3, 3), gm*GROWTH_RELATIVE)
  G[i] = 1.0 + GROWTH_RELATIVE*t*gm

  return G[i]
