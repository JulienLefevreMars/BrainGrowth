import numpy as np
import math
import numba
from numba import jit, njit, prange
from mathfunc import det_dim_3, det_dim_2, cross_dim_3, dot_mat_dim_3, transpose_dim_3, normalize_dim_3
import slam.io as sio
from scipy import spatial
from scipy.optimize import curve_fit
from slam import topology as stop
from curvatureCoarse import graph_laplacian
from scipy.sparse.linalg import eigs
from sklearn.cluster import KMeans
import scipy.special as spe

# Import mesh, each line as a list
def importMesh(path):
  mesh = []
  with open(path) as inputfile:
    for line in inputfile:
      mesh.append(line.strip().split(' '))
    for i in range(len(mesh)):
      mesh[i] = list(filter(None, mesh[i]))
      mesh[i] = np.array([float(a) for a in mesh[i]])
  #mesh = np.asarray(mesh, dtype=np.float64)
  return mesh

# Read nodes, get undeformed coordinates x y z and save them in Ut0, initialize deformed coordinates Ut
@njit(parallel=True)
def vertex(mesh):
  nn = np.int64(mesh[0][0])
  Ut0 = np.zeros((nn,3), dtype=np.float64) # Undeformed coordinates of nodes
  #Ut = np.zeros((nn,3), dtype = float) # Deformed coordinates of nodes
  for i in prange(nn):
    Ut0[i] = np.array([float(mesh[i+1][1]),float(mesh[i+1][0]),float(mesh[i+1][2])]) # Change x, y (Netgen?)
    
  Ut = Ut0 # Initialize deformed coordinates of nodes
  
  return Ut0, Ut, nn

# Read element indices (tets: index of four vertices of tetrahedra) and get number of elements (ne)
@njit(parallel=True)
def tetraVerticesIndices(mesh, nn):
  ne = np.int64(mesh[nn+1][0])
  tets = np.zeros((ne,4), dtype=np.int64) # Index of four vertices of tetrahedra
  for i in prange(ne):
    tets[i] = np.array([int(mesh[i+nn+2][1])-1,int(mesh[i+nn+2][2])-1,int(mesh[i+nn+2][4])-1,int(mesh[i+nn+2][3])-1])  # Note the switch of handedness (1,2,3,4 -> 1,2,4,3) - the code uses right handed tets
  
  return tets, ne

# Read surface triangle indices (faces: index of three vertices of triangles) and get number of surface triangles (nf)
@njit(parallel=True)
def triangleIndices(mesh, nn, ne):
  nf = np.int64(mesh[nn+ne+2][0])
  faces = np.zeros((nf,3), dtype=np.int64) # Index of three vertices of triangles
  for i in prange(nf):
    faces[i] = np.array([int(mesh[i+nn+ne+3][1])-1,int(mesh[i+nn+ne+3][2])-1,int(mesh[i+nn+ne+3][3])-1])

  return faces, nf

# Determine surface nodes and index maps
@jit
def numberSurfaceNodes(faces, nn, nf):
  nsn = 0 # Number of nodes at the surface
  SNb = np.zeros(nn, dtype=int) # SNb: Nodal index map from full mesh to surface. Initialization SNb with all 0
  SNb[faces[:,0]] = SNb[faces[:,1]] = SNb[faces[:,2]] = 1
  for i in range(nn):
    if SNb[i] == 1:
      nsn += 1 # Determine surface nodes
  SN = np.zeros(nsn, dtype=int) # SN: Nodal index map from surface to full mesh
  p = 0 # Iterator
  for i in range(nn):
    if SNb[i] == 1:
      SN[p] = i
      SNb[i] = p
      p += 1

  return nsn, SN, SNb

# Check minimum, maximum and average edge lengths (average mesh spacing) at the surface
@jit(nopython=True, parallel=True)
def edge_length(Ut, faces, nf):
  mine = 1e9
  maxe = ave = 0.0
  for i in range(nf):
    mine = min(np.linalg.norm(Ut[faces[i,1]] - Ut[faces[i,0]]), mine)
    mine = min(np.linalg.norm(Ut[faces[i,2]] - Ut[faces[i,0]]), mine)
    mine = min(np.linalg.norm(Ut[faces[i,2]] - Ut[faces[i,1]]), mine)
    maxe = max(np.linalg.norm(Ut[faces[i,1]] - Ut[faces[i,0]]), maxe)
    maxe = max(np.linalg.norm(Ut[faces[i,2]] - Ut[faces[i,0]]), maxe)
    maxe = max(np.linalg.norm(Ut[faces[i,2]] - Ut[faces[i,1]]), maxe)
    ave += np.linalg.norm(Ut[faces[i,2]] - Ut[faces[i,1]]) + np.linalg.norm(Ut[faces[i,2]] - Ut[faces[i,0]]) + np.linalg.norm(Ut[faces[i,1]] - Ut[faces[i,0]])
  ave /= 3.0*nf

  return mine, maxe, ave

# Return the total volume of a tetrahedral mesh
@jit(nopython=True, parallel=True)
def volume_mesh(Vn_init, nn, ne, tets, Ut):
  A_init = np.zeros((ne,3,3), dtype=np.float64)
  vol_init = np.zeros(ne, dtype=np.float64)

  A_init[:,0] = Ut[tets[:,1]] - Ut[tets[:,0]]
  A_init[:,1] = Ut[tets[:,2]] - Ut[tets[:,0]]
  A_init[:,2] = Ut[tets[:,3]] - Ut[tets[:,0]]
  vol_init[:] = det_dim_3(transpose_dim_3(A_init[:]))/6.0

  for i in range(ne):
    #vol_init[i] = np.linalg.det(np.transpose(A_init[i]))/6.0
    Vn_init[tets[i,:]] += vol_init[i]/4.0

  Vm_init = np.sum(Vn_init)

  return Vm_init

# Define the label for each surface node for half brain
@jit
def tetra_labels_surface_half(mesh_file, method, n_clusters, Ut0, SN, tets, lobes):
  mesh = sio.load_mesh(mesh_file)
  if method.__eq__("Kmeans"):
  # 1) Simple K-means to start simply
    kmeans = KMeans(n_clusters=n_clusters, random_state=0).fit(mesh.vertices)
    labels = kmeans.labels_
  elif method.__eq__("Spectral"):
  # 2) Another method: spectral clustering
    Lsparse = graph_laplacian(mesh)
    evals, evecs = eigs(Lsparse, k=n_clusters - 1, which='SM')
    kmeans = KMeans(n_clusters=n_clusters, random_state=0).fit(np.real(evecs))
    labels = kmeans.labels_
  #kmeans = KMeans(n_clusters=n_clusters, random_state=0).fit(mesh.vertices)
  labels = lobes #kmeans.labels_ 
  # Find the nearest reference surface nodes to our surface nodes (csn) and distribute the labels to our surface nodes (labels_surface)
  mesh.vertices[:,[0,1]]=mesh.vertices[:,[1,0]]
  tree = spatial.KDTree(mesh.vertices)
  csn = tree.query(Ut0[SN[:]])
  #labels_surface = np.zeros(nsn, dtype = np.int64)
  #labels_surface_2 = np.zeros(nsn, dtype = np.int64)
  labels_surface = labels[csn[1]]

  return labels_surface, labels

# Define the label for each tetrahedron for half brain
@jit
def tetra_labels_volume_half(Ut0, SN, tets, labels_surface):
  # Find the nearest surface nodes to barycenters of tetahedra (csn_t) and distribute the label to each tetahedra (labels_volume)
  Ut_barycenter = (Ut0[tets[:,0]] + Ut0[tets[:,1]] + Ut0[tets[:,2]] + Ut0[tets[:,3]])/4.0
  tree = spatial.KDTree(Ut0[SN[:]])
  csn_t = tree.query(Ut_barycenter[:,:])
  #labels_volume = np.zeros(ne, dtype = np.int64)
  labels_volume = labels_surface[csn_t[1]]

  return labels_volume

# Define the label for each surface node for whole brain
@jit
def tetra_labels_surface_whole(mesh_file, mesh_file_2, method, n_clusters, Ut0, SN, tets, indices_a, indices_b, lobes, lobes_2):
  mesh = sio.load_mesh(mesh_file)
  mesh_2 = sio.load_mesh(mesh_file_2)
  if method.__eq__("Kmeans"):
  # 1) Simple K-means to start simply
    kmeans = KMeans(n_clusters=n_clusters, random_state=0).fit(mesh.vertices)
    kmeans_2 = KMeans(n_clusters=n_clusters, random_state=0).fit(mesh_2.vertices)
    labels = kmeans.labels_
    labels_2 = kmeans_2.labels_
  elif method.__eq__("Spectral"):
  # 2) Another method: spectral clustering
    Lsparse = graph_laplacian(mesh)
    Lsparse_2 = graph_laplacian(mesh_2)
    evals, evecs = eigs(Lsparse, k=n_clusters - 1, which='SM')
    evals_2, evecs_2 = eigs(Lsparse_2, k=n_clusters - 1, which='SM')
    kmeans = KMeans(n_clusters=n_clusters, random_state=0).fit(np.real(evecs))
    kmeans_2 = KMeans(n_clusters=n_clusters, random_state=0).fit(np.real(evecs_2))
    labels = kmeans.labels_
    labels_2 = kmeans_2.labels_
  #kmeans = KMeans(n_clusters=n_clusters, random_state=0).fit(mesh.vertices)
  labels = lobes #kmeans.labels_
  labels_2 = lobes_2 #kmeans_2.labels_ 
  # Find the nearest reference surface nodes to our surface nodes (csn) and distribute the labels to our surface nodes (labels_surface)
  mesh.vertices[:,[0,1]]=mesh.vertices[:,[1,0]]
  mesh_2.vertices[:,[0,1]]=mesh_2.vertices[:,[1,0]]
  tree_1 = spatial.KDTree(mesh.vertices)
  tree_2 = spatial.KDTree(mesh_2.vertices)
  csn = tree_1.query(Ut0[SN[indices_a]])
  csn_2 = tree_2.query(Ut0[SN[indices_b]])
  #labels_surface = np.zeros(nsn, dtype = np.int64)
  #labels_surface_2 = np.zeros(nsn, dtype = np.int64)
  labels_surface = labels[csn[1]]
  labels_surface_2 = labels_2[csn_2[1]]

  return labels_surface, labels_surface_2, labels, labels_2

# Define the label for each tetrahedron for whole brain
@jit
def tetra_labels_volume_whole(Ut0, SN, tets, indices_a, indices_b, indices_c, indices_d, labels_surface, labels_surface_2):
  # Find the nearest surface nodes to barycenters of tetahedra (csn_t) and distribute the label to each tetahedra (labels_volume)
  #indices_c = np.where((Ut0[tets[:,0],1]+Ut0[tets[:,1],1]+Ut0[tets[:,2],1]+Ut0[tets[:,3],1])/4 >= 0.0)[0]  #lower part
  #indices_d = np.where((Ut0[tets[:,0],1]+Ut0[tets[:,1],1]+Ut0[tets[:,2],1]+Ut0[tets[:,3],1])/4 < 0.0)[0]  #upper part
  Ut_barycenter_c = (Ut0[tets[indices_c,0]] + Ut0[tets[indices_c,1]] + Ut0[tets[indices_c,2]] + Ut0[tets[indices_c,3]])/4.0
  Ut_barycenter_d = (Ut0[tets[indices_d,0]] + Ut0[tets[indices_d,1]] + Ut0[tets[indices_d,2]] + Ut0[tets[indices_d,3]])/4.0
  tree_3 = spatial.KDTree(Ut0[SN[indices_a]])
  csn_t = tree_3.query(Ut_barycenter_c[:,:])
  tree_4 = spatial.KDTree(Ut0[SN[indices_b]])
  csn_t_2 = tree_4.query(Ut_barycenter_d[:,:])
  #labels_volume = np.zeros(ne, dtype = np.int64)
  labels_volume = labels_surface[csn_t[1]]
  labels_volume_2 = labels_surface_2[csn_t_2[1]]

  return labels_volume, labels_volume_2

# Define Gaussian function for temporal growth rate
@jit
def func(x, a, c, sigma):

  return a*np.exp(-(x-c)**2/sigma)

# Define asymmetric normal function for temporal growth rate
@jit
def skew(X, a, e, w):
  X = (X-e)/w
  Y = 2*np.exp(-X**2/2)/np.sqrt(2*np.pi)
  Y *= 1/w*spe.ndtr(a*X)  #ndtr: gaussian cumulative distribution function
  
  return Y

# Define polynomial for temporal growth
@jit
def poly(x, a, b, c):
  
  return a*x**2+b*x+c

# Define gompertz model for temporal growth
@jit
def gompertz(x, a, b, c):

  return a*np.exp(-np.exp(-b*(x-c)))

# Curve-fit of temporal growth for each label for half brain
#@jit
def Curve_fitting_half(texture_file, labels, n_clusters, lobes):
  ages=[29, 29, 28, 28.5, 31.5, 32, 31, 32, 30.5, 32, 32, 31, 35.5, 35, 34.5, 35, 34.5, 35, 36, 34.5, 37.5, 35, 34.5, 36, 34.5, 33, 33]
  xdata=np.array(ages)
  
  croissance_globale_R = np.array([1.30, 1.56, 1.22, 1.46, 1.35,1.24,1.47,1.58,1.45,1.31,1.66,1.78,1.67,1.42,1.44,1.22,1.75,1.56,1.40,1.33,1.79,1.27,1.52,1.34,1.68,1.81,1.78])

  # Calculate the local (true) cortical growth
  texture = sio.load_texture(texture_file)
  texture_sujet2_R = np.array([texture.darray[1], texture.darray[5], texture.darray[13]])
  
  ages_sujet2 = np.array([31, 33, 37, 44])
  tp_model = 6.926*10**(-5)*ages_sujet2**3-0.00665*ages_sujet2**2+0.250*ages_sujet2-3.0189  #time of numerical model
  croissance_globale_sujet2_R = np.array([croissance_globale_R[1], croissance_globale_R[5], croissance_globale_R[13]])
  croissance_true_relative_R = np.zeros(texture_sujet2_R.shape)
  for i in range(texture_sujet2_R.shape[0]):
    croissance_true_relative_R[i, :] = texture_sujet2_R[i,:]*croissance_globale_sujet2_R[i]

  latency=np.zeros(len(np.unique(lobes)), dtype=np.float64)
  amplitude=np.zeros(len(np.unique(lobes)), dtype=np.float64)
  peak=np.zeros(len(np.unique(lobes)), dtype=np.float64)
  ydata=np.zeros((3, len(np.unique(lobes))), dtype = np.float64)
  ydata_new=np.zeros((4, len(np.unique(lobes))), dtype = np.float64)
  
  p = 0
  for k in np.unique(lobes):      #= int(np.unique(lobes)[5])
    for j in range(texture_sujet2_R.shape[0]):
      ydata[j, p]=np.mean(croissance_true_relative_R[j, np.where(lobes == k)[0]])
    p += 1
  ydata_new[0,:] = ydata[0,:]-1
  ydata_new[1,:] = ydata[0, :]*ydata[1, :]-1
  ydata_new[2,:] = ydata[0, :]*ydata[1, :]*ydata[2, :]-1
  ydata_new[3,:] = np.full(len(np.unique(lobes)), 1.829)

  m = 0
  for j in range(len(np.unique(lobes))):    
    popt, pcov = curve_fit(gompertz, tp_model, ydata_new[:,j])   
    peak[m]=popt[1]
    amplitude[m]=popt[0]
    latency[m]=popt[2]
    #multiple[m]=popt[3]
    m += 1

  return peak, amplitude, latency

# Curve-fit of temporal growth for each label for whole brain
#@jit
def Curve_fitting_whole(texture_file, texture_file_2, labels, labels_2, n_clusters, lobes, lobes_2):
  ages=[29, 29, 28, 28.5, 31.5, 32, 31, 32, 30.5, 32, 32, 31, 35.5, 35, 34.5, 35, 34.5, 35, 36, 34.5, 37.5, 35, 34.5, 36, 34.5, 33, 33]
  xdata=np.array(ages)
  
  croissance_globale_L = np.array([1.26, 1.51, 1.21, 1.38, 1.37, 1.22, 1.44, 1.57, 1.45, 1.34, 1.54, 1.67, 1.70, 1.48, 1.50, 1.19, 1.78, 1.59, 1.49, 1.34, 1.77, 1.29 ,1.57, 1.45, 1.71, 1.76, 1.81])
  croissance_globale_R = np.array([1.30, 1.56, 1.22, 1.46, 1.35,1.24,1.47,1.58,1.45,1.31,1.66,1.78,1.67,1.42,1.44,1.22,1.75,1.56,1.40,1.33,1.79,1.27,1.52,1.34,1.68,1.81,1.78])
  """xdata_new = np.zeros(5)
  xdata_new[0]=22
  xdata_new[1]=27
  xdata_new[2]=31
  xdata_new[3]=33
  xdata_new[4]=37"""
  #tp_model = 6.926*10**(-5)*xdata**3-0.00665*xdata**2+0.250*xdata-3.0189  #time of numerical model

  # Calculate the local (true) cortical growth
  """popt, pcov = curve_fit(poly, np.array([27, 31, 33, 37]), np.array([1, 1.26, 1.26*1.37, 1.26*1.37*1.70]))
  croissance_globale = np.array(poly(xdata,*popt))"""

  texture = sio.load_texture(texture_file)
  texture_2 = sio.load_texture(texture_file_2)
  texture_sujet2_R = np.array([texture.darray[1], texture.darray[5], texture.darray[13]])
  texture_sujet2_L = np.array([texture_2.darray[1], texture_2.darray[5], texture_2.darray[13]])
  
  ages_sujet2 = np.array([31, 33, 37, 44])
  tp_model = 6.926*10**(-5)*ages_sujet2**3-0.00665*ages_sujet2**2+0.250*ages_sujet2-3.0189  #time of numerical model
  croissance_globale_sujet2_R = np.array([croissance_globale_R[1], croissance_globale_R[5], croissance_globale_R[13]])
  croissance_globale_sujet2_L = np.array([croissance_globale_L[1], croissance_globale_L[5], croissance_globale_L[13]])
  croissance_true_relative_R = np.zeros(texture_sujet2_R.shape)
  croissance_true_relative_L = np.zeros(texture_sujet2_L.shape)
  for i in range(texture_sujet2_R.shape[0]):
    croissance_true_relative_R[i, :] = texture_sujet2_R[i,:]*croissance_globale_sujet2_R[i]
    croissance_true_relative_L[i, :] = texture_sujet2_L[i,:]*croissance_globale_sujet2_L[i]
  """croissance_true = np.zeros(texture.darray.shape, dtype=np.float64)
  for i in range(texture.darray.shape[0]):
    croissance_true[i,:] = texture.darray[i,:]*croissance_globale[i]
  croissance_length = np.sqrt(croissance_true)

  texture_2 = sio.load_texture(texture_file_2)
  croissance_true_2 = np.zeros(texture_2.darray.shape, dtype=np.float64)
  for j in range(texture_2.darray.shape[0]):
    croissance_true_2[j,:] = texture_2.darray[j,:]*croissance_globale[j]
  croissance_length_2 = np.sqrt(croissance_true_2)"""

  """peak=np.zeros((n_clusters,))
  amplitude=np.zeros((n_clusters,))
  latency=np.zeros((n_clusters,))
  peak_2=np.zeros((n_clusters,))
  amplitude_2=np.zeros((n_clusters,))
  latency_2=np.zeros((n_clusters,))
  for k in range(n_clusters):
    ydata=np.mean(croissance_length[:,np.where(labels == k)[0]], axis=1)
    ydata_2=np.mean(croissance_length_2[:,np.where(labels_2 == k)[0]], axis=1)
    popt, pcov=curve_fit(func, tp_model, ydata, p0=[1.5, 0.9, 0.09])
    popt_2, pcov_2=curve_fit(func, tp_model, ydata_2, p0=[1.5, 0.9, 0.09])
    peak[k]=popt[1]   
    amplitude[k]=popt[0]
    latency[k]=popt[2]
    peak_2[k]=popt_2[1]   
    amplitude_2[k]=popt_2[0]
    latency_2[k]=popt_2[2]"""

  latency=np.zeros(len(np.unique(lobes)), dtype=np.float64)
  amplitude=np.zeros(len(np.unique(lobes)), dtype=np.float64)
  peak=np.zeros(len(np.unique(lobes)), dtype=np.float64)
  latency_2=np.zeros(len(np.unique(lobes_2)), dtype=np.float64)
  amplitude_2=np.zeros(len(np.unique(lobes_2)), dtype=np.float64)
  peak_2=np.zeros(len(np.unique(lobes_2)), dtype=np.float64)
  ydata=np.zeros((3, len(np.unique(lobes))), dtype = np.float64)
  ydata_new=np.zeros((4, len(np.unique(lobes))), dtype = np.float64)
  ydata_2=np.zeros((3, len(np.unique(lobes_2))), dtype = np.float64)
  ydata_new_2=np.zeros((4, len(np.unique(lobes_2))), dtype = np.float64)

  #for k in range(n_clusters):  
  """m = 0
  for k in np.unique(lobes):
    #ydata=np.mean(texture_new[:,np.where(labels == k)[0]], axis=1)
    #ydata_2=np.mean(texture_new_2[:,np.where(labels_2 == k)[0]], axis=1)
    ydata=np.mean(croissance_length[:, np.where(lobes == k)[0]], axis=1)
    popt, pcov=curve_fit(gompertz, tp_model, ydata, p0=[0.94, 2.16, 3.51, 1.0]) #p0=[1.5, 0.9, 0.09] =[0.94, 2.16, 3.51, 0.65])
    peak[m]=popt[1]
    amplitude[m]=popt[0]
    latency[m]=popt[2]
    multiple[m]=popt[3]
    m += 1
  m_2 = 0
  for k in np.unique(lobes_2):
    ydata_2=np.mean(croissance_length_2[:, np.where(lobes_2 == k)[0]], axis=1)
    popt_2, pcov_2=curve_fit(gompertz, tp_model, ydata_2, p0=[0.94, 2.16, 3.51, 1.0])
    peak_2[m_2]=popt_2[1]   
    amplitude_2[m_2]=popt_2[0]
    latency_2[m_2]=popt_2[2]
    multiple_2[m_2]=popt_2[3]
    m_2 += 1"""
  
  p = 0
  for k in np.unique(lobes):      #= int(np.unique(lobes)[5])
    for j in range(texture_sujet2_R.shape[0]):
      ydata[j, p]=np.mean(croissance_true_relative_R[j, np.where(lobes == k)[0]])
    p += 1
  ydata_new[0,:] = ydata[0,:]-1
  ydata_new[1,:] = ydata[0, :]*ydata[1, :]-1
  ydata_new[2,:] = ydata[0, :]*ydata[1, :]*ydata[2, :]-1
  ydata_new[3,:] = np.full(len(np.unique(lobes)), 1.829)

  m = 0
  for j in range(len(np.unique(lobes))):    
    popt, pcov = curve_fit(gompertz, tp_model, ydata_new[:,j])   
    peak[m]=popt[1]
    amplitude[m]=popt[0]
    latency[m]=popt[2]
    #multiple[m]=popt[3]
    m += 1

  p_2 = 0
  for k in np.unique(lobes_2):
    for j in range(texture_sujet2_L.shape[0]):
      ydata_2[j, p_2]=np.mean(croissance_true_relative_L[j, np.where(lobes_2 == k)[0]])
    p_2 += 1
  ydata_new_2[0,:] = ydata_2[0,:]-1
  ydata_new_2[1,:] = ydata_2[0, :]*ydata_2[1, :]-1
  ydata_new_2[2,:] = ydata_2[0, :]*ydata_2[1, :]*ydata_2[2, :]-1
  ydata_new_2[3,:] = np.full(len(np.unique(lobes_2)), 1.829)

  m_2 = 0
  for j in range(len(np.unique(lobes_2))):    
    popt_2, pcov_2 = curve_fit(gompertz, tp_model, ydata_new_2[:,j])   
    peak_2[m_2]=popt_2[1]
    amplitude_2[m_2]=popt_2[0]
    latency_2[m_2]=popt_2[2]
    #multiple_2[m_2]=popt[3]
    m_2 += 1

  return peak, amplitude, latency, peak_2, amplitude_2, latency_2

# Mark non-growing areas
@njit(parallel=True)
def markgrowth(Ut0, nn):
  gr = np.zeros(nn, dtype = np.float64)
  for i in prange(nn):
    rqp = np.linalg.norm(np.array([(Ut0[i,0]+0.1)*0.714, Ut0[i,1], Ut0[i,2]-0.05]))
    if rqp < 0.6:
      gr[i] = max(1.0 - 10.0*(0.6-rqp), 0.0)
    else:
      gr[i] = 1.0

  return gr

# Configuration of tetrahedra at reference state (A0)
@jit
def configRefer(Ut0, tets, ne):
  A0 = np.zeros((ne,3,3), dtype=np.float64)
  A0[:,0] = Ut0[tets[:,1]] - Ut0[tets[:,0]] # Reference state
  A0[:,1] = Ut0[tets[:,2]] - Ut0[tets[:,0]]
  A0[:,2] = Ut0[tets[:,3]] - Ut0[tets[:,0]]
  A0[:] = transpose_dim_3(A0[:])

  return A0

# Configuration of a deformed tetrahedron (At)
@jit
def configDeform(Ut, tets, ne):
  At = np.zeros((ne,3,3), dtype=np.float64)
  At[:,0] = Ut[tets[:,1]] - Ut[tets[:,0]]
  At[:,1] = Ut[tets[:,2]] - Ut[tets[:,0]]
  At[:,2] = Ut[tets[:,3]] - Ut[tets[:,0]]
  #At = np.matrix([x1, x2, x3])
  At[:] = transpose_dim_3(At[:])

  return At

# Calculate normals of each surface triangle and apply these normals to surface nodes
@jit(nopython=True, parallel=True) 
def normalSurfaces(Ut0, faces, SNb, nf, nsn, N0):
  Ntmp = np.zeros((nf,3), dtype=np.float64)
  Ntmp = cross_dim_3(Ut0[faces[:,1]] - Ut0[faces[:,0]], Ut0[faces[:,2]] - Ut0[faces[:,0]])
  for i in range(nf):
    N0[SNb[faces[i,:]]] += Ntmp[i]
  for i in range(nsn):
    N0[i] *= 1.0/np.linalg.norm(N0[i])
  #N0 = normalize_dim_3(N0)

  return N0

# Calculate normals of each deformed tetrahedron
@jit
def tetraNormals(N0, csn, tets, ne):
  Nt = np.zeros((ne,3), dtype=np.float64)
  Nt[:] = N0[csn[tets[:,0]]] + N0[csn[tets[:,1]]] + N0[csn[tets[:,2]]] + N0[csn[tets[:,3]]]
  Nt = normalize_dim_3(Nt)
  """for i in prange(ne):
    Nt[i] *= 1.0/np.linalg.norm(Nt[i])"""

  return Nt

# Calculate undeformed (Vn0) and deformed (Vn) nodal volume
# Computes the volume measured at each point of a tetrahedral mesh as the sum of 1/4 of the volume of each of the tetrahedra to which it belongs
@jit(nopython=True, parallel=True)   #(nopython=True, parallel=True)
def volumeNodal(G, A0, tets, Ut, ne, nn):
  Vn0 = np.zeros(nn, dtype=np.float64) #Initialize nodal volumes in reference state
  Vn = np.zeros(nn, dtype=np.float64)  #Initialize deformed nodal volumes
  At = np.zeros((ne,3,3), dtype=np.float64)
  vol0 = np.zeros(ne, dtype=np.float64)
  vol = np.zeros(ne, dtype=np.float64)
  At[:,0] = Ut[tets[:,1]] - Ut[tets[:,0]]
  At[:,1] = Ut[tets[:,2]] - Ut[tets[:,0]]
  At[:,2] = Ut[tets[:,3]] - Ut[tets[:,0]]
  vol0[:] = det_dim_3(dot_mat_dim_3(G[:], A0[:]))/6.0
  #vol0[:] = det_dim_3(dot_const_mat_dim_3(G, A0[:]))/6.0
  vol[:] = det_dim_3(transpose_dim_3(At[:]))/6.0
  for i in range(ne):
    #vol0[i] = np.linalg.det(np.dot(G[i], A0[i]))/6.0
    #vol[i] = np.linalg.det(np.transpose(At[i]))/6.0
    Vn0[tets[i,:]] += vol0[i]/4.0
    Vn[tets[i,:]] += vol[i]/4.0

  return Vn0, Vn

# Midplane
@njit(parallel=True)
def midPlane(Ut, Ut0, Ft, SN, nsn, mpy, a, hc, K):
  for i in prange(nsn):
    pt = SN[i]
    if Ut0[pt,1] < mpy - 0.5*a and Ut[pt,1] > mpy:
      Ft[pt,1] -= (mpy - Ut[pt,1])/hc*a*a*K
    if Ut0[pt,1] > mpy + 0.5*a and Ut[pt,1] < mpy:
      Ft[pt,1] -= (mpy - Ut[pt,1])/hc*a*a*K

  return Ft

# Calculate the longitudinal length of the real brain
@jit
def longitLength(t):
  #L = -0.81643*t**2+2.1246*t+1.3475
  L = -0.98153*t**2+3.4214*t+1.9936
  #L = -41.6607*t**2+101.7986*t+58.843 #for the case without normalisation

  return L

# Obtain zoom parameter by checking the longitudinal length of the brain model
@jit
def paraZoom(Ut, SN, L, nsn):
  #xmin = ymin = 1.0
  #xmax = ymax = -1.0

  xmin = min(Ut[SN[:],0])
  xmax = max(Ut[SN[:],0])
  ymin = min(Ut[SN[:],1])
  ymax = max(Ut[SN[:],1])

  # Zoom parameter
  zoom_pos = L/(xmax-xmin)

  return zoom_pos
