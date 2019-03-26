import numpy as np
import math
from numba import jit

# Normalize initial mesh coordinates
@jit
def normalisation(Ut0, Ut, nn):
  # Find center of mass and dimension of the mesh
  maxx, minx, maxy, miny, maxz, minz  = -1e9, 1e9, -1e9, 1e9, -1e9, 1e9
  cog = np.array([0.0, 0.0, 0.0])
  for i in range(nn):
    maxx = max(maxx, Ut0[i][0])
    minx = min(minx, Ut0[i][0])
    maxy = max(maxy, Ut0[i][1])
    miny = min(miny, Ut0[i][1])
    maxz = max(maxz, Ut0[i][2])
    minz = min(minz, Ut0[i][2])
    cog += Ut0[i]
  # The center coordinate(x,y,z)
  cog /= nn

  #print ('minx is ' + str(minx) + ' maxx is ' + str(maxx) + ' miny is ' + str(miny) + ' maxy is ' + str(maxy) + ' minz is ' + str(minz) + ' maxz is ' + str(maxz))
  #print ('center x is ' + str(cog[0]) + ' center y is ' + str(cog[1]) + ' center z is ' + str(cog[2]))

  # Change mesh information by values normalized
  maxd = max(max(max(abs(maxx-cog[0]), abs(minx-cog[0])), max(abs(maxy-cog[1]), abs(miny-cog[1]))), max(abs(maxz-cog[2]), abs(minz-cog[2])))  # The biggest value of difference between the coordinate(x, y, z) and center(x, y,z) respectively
  for i in range(nn):
    Ut0[i][0] = -(Ut[i][0] - cog[0])/maxd
    Ut0[i][1] = (Ut[i][1] - cog[1])/maxd
    Ut0[i][2] = -(Ut[i][2] - cog[2])/maxd
    Ut[i] = Ut0[i]

  return Ut0, Ut