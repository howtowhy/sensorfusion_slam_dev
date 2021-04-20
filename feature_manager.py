"""
* This file is part of PYSLAM 
*
* Copyright (C) 2016-present Luigi Freda <luigi dot freda at gmail dot com> 
*
* PYSLAM is free software: you can redistribute it and/or modify
* it under the terms of the GNU General Public License as published by
* the Free Software Foundation, either version 3 of the License, or
* (at your option) any later version.
*
* PYSLAM is distributed in the hope that it will be useful,
* but WITHOUT ANY WARRANTY; without even the implied warranty of
* MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
* GNU General Public License for more details.
*
* You should have received a copy of the GNU General Public License
* along with PYSLAM. If not, see <http://www.gnu.org/licenses/>.
"""
import sys 
import math 
import numpy as np
import cv2

from collections import Counter

from parameters import Parameters  

from feature_types import FeatureDetectorTypes, FeatureDescriptorTypes, FeatureInfo

from utils import Printer, import_from
from utils_features import unpackSiftOctaveKps, UnpackOctaveMethod, sat_num_features, kdt_nms, ssc_nms, octree_nms, grid_nms
from utils_geom import hamming_distance, hamming_distances, l2_distance, l2_distances

from feature_manager_adaptors import BlockAdaptor, PyramidAdaptor
from pyramid import Pyramid, PyramidType

# import and check 
Orbslam2Feature2D = import_from('feature_orbslam2', 'Orbslam2Feature2D')

kVerbose = True   

kNumFeatureDefault = Parameters.kNumFeatures

kNumLevelsDefault = 4
kScaleFactorDefault = 1.2 

kNumLevelsInitSigma = 40

kSigmaLevel0 = Parameters.kSigmaLevel0 

kDrawOriginalExtractedFeatures = False  # for debugging 

kFASTKeyPointSizeRescaleFactor = 4        # 7 is the standard keypoint size on layer 0  => actual size = 7*kFASTKeyPointSizeRescaleFactor
kAGASTKeyPointSizeRescaleFactor = 4       # 7 is the standard keypoint size on layer 0  => actual size = 7*kAGASTKeyPointSizeRescaleFactor
kShiTomasiKeyPointSizeRescaleFactor = 5   # 5 is the selected keypoint size on layer 0 (see below) => actual size = 5*kShiTomasiKeyPointSizeRescaleFactor


if not kVerbose:
    def print(*args, **kwargs):
        pass


def feature_manager_factory(num_features=kNumFeatureDefault, 
                            num_levels = kNumLevelsDefault,                  # number of pyramid levels or octaves for detector and descriptor
                            scale_factor = kScaleFactorDefault,              # detection scale factor (if it can be set, otherwise it is automatically computed)
                            detector_type = FeatureDetectorTypes.ORB2,
                            descriptor_type = FeatureDescriptorTypes.ORB2):
    return FeatureManager(num_features, num_levels, scale_factor, detector_type, descriptor_type)


# Manager of both detector and descriptor 
# This exposes an interface that is similar to OpenCV::Feature2D, i.e. detect(), compute() and detectAndCompute()
class FeatureManager(object):
    def __init__(self, num_features=kNumFeatureDefault, 
                       num_levels = kNumLevelsDefault,                         # number of pyramid levels or octaves for detector and descriptor
                       scale_factor = kScaleFactorDefault,                     # detection scale factor (if it can be set, otherwise it is automatically computed)
                       detector_type = FeatureDetectorTypes.ORB2,
                       descriptor_type = FeatureDescriptorTypes.ORB2):
        self.detector_type = detector_type 
        self._feature_detector   = None 
                
        self.descriptor_type = descriptor_type
        self._feature_descriptor = None 
                
        # main feature manager properties 
        self.num_features = num_features
        self.num_levels = num_levels  
        self.first_level = 0              # not always applicable = > 0: start pyramid from input image; 
                                          #                          -1: start pyramid from up-scaled image*scale_factor (as in SIFT)
        self.scale_factor = scale_factor  # scale factor bewteen two octaves 
        self.sigma_level0 = kSigmaLevel0  # sigma on first octave 
        self.layers_per_octave = 3        # for methods that uses octaves (SIFT, SURF, etc)
        
        # feature norm options  
        self.norm_type = None            # descriptor norm type 
        self.descriptor_distance = None  # pointer to a function for computing the distance between two points 
        self.descriptor_distances = None # pointer to a function for computing the distances between two array of corresponding points    
                
        # block adaptor options 
        self.use_bock_adaptor = False 
        self.block_adaptor = None
        
        # pyramid adaptor options: at present time pyramid adaptor has the priority and can combine a block adaptor withint itself         
        self.use_pyramid_adaptor = False 
        self.pyramid_adaptor = None 
        self.pyramid_type = PyramidType.RESIZE
        self.pyramid_do_parallel = True
        self.do_sat_features_per_level = False  # if pyramid adaptor is active, one can require to compute a certain number of features per level (see PyramidAdaptor)
        self.force_multiscale_detect_and_compute = False # automatically managed below depending on features 
        
        self.oriented_features = True             # automatically managed below depending on selected features 
        self.do_keypoints_size_rescaling = False  # automatically managed below depending on selected features 
        self.need_color_image = False             # automatically managed below depending on selected features

        # initialize sigmas for keypoint levels (used for SLAM)
        self.init_sigma_levels()
        
        # --------------------------------------------- #
        # manage different opencv versions  
        # --------------------------------------------- #
        print("using opencv ", cv2.__version__)
        # check opencv version in order to use the right modules 
        if cv2.__version__.split('.')[0] == '3':
            ORB_create = import_from('cv2','ORB_create')
        else:
            ORB_create = import_from('cv2','ORB')

        # pure detectors
        # detectors and descriptors 
        self.ORB_create = ORB_create

        # --------------------------------------------- #
        # check if we want descriptor == detector   
        # --------------------------------------------- #
        self.is_detector_equal_to_descriptor = (self.detector_type.name == self.descriptor_type.name)
            
        self.orb_params = dict(nfeatures=num_features,
                               scaleFactor=self.scale_factor,
                               nlevels=self.num_levels,
                               patchSize=31,
                               edgeThreshold = 10, #31, #19, #10,   # margin from the frame border 
                               fastThreshold = 20,
                               firstLevel = self.first_level,
                               WTA_K = 2,
                               scoreType=cv2.ORB_FAST_SCORE)  #scoreType=cv2.ORB_HARRIS_SCORE, scoreType=cv2.ORB_FAST_SCORE 
        
        # --------------------------------------------- #
        # init detector 
        # --------------------------------------------- #
        if self.detector_type == FeatureDetectorTypes.ORB2:
            orb2_num_levels = self.num_levels                              
            self._feature_detector = Orbslam2Feature2D(self.num_features, self.scale_factor, orb2_num_levels) 
            self.keypoint_filter_type = None  # ORB2 cpp implementation already includes the algorithm OCTREE_NMS
        else:
            raise ValueError("Unknown feature detector %s" % self.detector_type)
        
        if self.use_bock_adaptor: 
              self.orb_params['edgeThreshold'] = 0
                  
        # --------------------------------------------- #
        # init descriptor 
        # --------------------------------------------- #                     
        if self.is_detector_equal_to_descriptor:     
            Printer.green('using same detector and descriptor object: ', self.detector_type.name)
            self._feature_descriptor = self._feature_detector
        else:      
            # detector and descriptors are different             
            self.num_levels_descriptor = self.num_levels                    
            if self.use_pyramid_adaptor:        
                # NOT VALID ANYMORE -> if there is a pyramid adaptor, the descriptor does not need to rescale the images which are rescaled by the pyramid adaptor itself              
                #self.orb_params['nlevels'] = 1    
                #self.num_levels_descriptor = 1 #self.num_levels
                pass 
            # actual descriptor initialization 
            if self.descriptor_type == FeatureDescriptorTypes.ORB2:
                self._feature_descriptor = self.ORB_create(**self.orb_params)
            else:
                raise ValueError("Unknown feature descriptor %s" % self.descriptor_type)    
            
        # --------------------------------------------- #
        # init from FeatureInfo   
        # --------------------------------------------- #               
        
        # get and set norm type 
        try: 
            self.norm_type = FeatureInfo.norm_type[self.descriptor_type]
        except:
            Printer.red('You did not set the norm type for: ', self.descriptor_type.name)              
            raise ValueError("Unmanaged norm type for feature descriptor %s" % self.descriptor_type.name)     
        
        # set descriptor distance functions  
        if self.norm_type == cv2.NORM_HAMMING:
            self.descriptor_distance = hamming_distance
            self.descriptor_distances = hamming_distances            
        if self.norm_type == cv2.NORM_L2:
            self.descriptor_distance = l2_distance      
            self.descriptor_distances = l2_distances         
            
         # get and set reference max descriptor distance      
        try: 
            Parameters.kMaxDescriptorDistance = FeatureInfo.max_descriptor_distance[self.descriptor_type]
        except: 
            Printer.red('You did not set the reference max descriptor distance for: ', self.descriptor_type.name)                                                         
            raise ValueError("Unmanaged max descriptor distance for feature descriptor %s" % self.descriptor_type.name)                
        Parameters.kMaxDescriptorDistanceSearchEpipolar = Parameters.kMaxDescriptorDistance                    
                
        # --------------------------------------------- #
        # other required initializations  
        # --------------------------------------------- #      
        
        if not self.oriented_features:
            Printer.orange('WARNING: using NON-ORIENTED features: ', self.detector_type.name,'-',self.descriptor_type.name, ' (i.e. kp.angle=0)')     
                        
        if self.is_detector_equal_to_descriptor:
            self.init_sigma_levels_sift()                 
        else: 
            self.init_sigma_levels()    
            
        if self.use_bock_adaptor:
            self.block_adaptor = BlockAdaptor(self._feature_detector, self._feature_descriptor)

        if self.use_pyramid_adaptor:   
            self.pyramid_params = dict(detector=self._feature_detector, 
                                       descriptor=self._feature_descriptor, 
                                       num_features = self.num_features,
                                       num_levels=self.num_levels, 
                                       scale_factor=self.scale_factor, 
                                       sigma0=self.sigma_level0, 
                                       first_level=self.first_level, 
                                       pyramid_type=self.pyramid_type,
                                       use_block_adaptor=self.use_bock_adaptor,
                                       do_parallel = self.pyramid_do_parallel,
                                       do_sat_features_per_level = self.do_sat_features_per_level)       
            self.pyramid_adaptor = PyramidAdaptor(**self.pyramid_params)


    # initialize scale factors, sigmas for each octave level; 
    # these are used for managing image pyramids and weighting (information matrix) reprojection error terms in the optimization
    def init_sigma_levels(self): 
        print('num_levels: ', self.num_levels)               
        num_levels = max(kNumLevelsInitSigma, self.num_levels)    
        self.inv_scale_factor = 1./self.scale_factor      
        self.scale_factors = np.zeros(num_levels)
        self.level_sigmas2 = np.zeros(num_levels)
        self.level_sigmas = np.zeros(num_levels)                
        self.inv_scale_factors = np.zeros(num_levels)
        self.inv_level_sigmas2 = np.zeros(num_levels)
        self.log_scale_factor = math.log(self.scale_factor)

        self.scale_factors[0] = 1.0                   
        self.level_sigmas2[0] = self.sigma_level0*self.sigma_level0
        self.level_sigmas[0] = math.sqrt(self.level_sigmas2[0])
        for i in range(1,num_levels):
            self.scale_factors[i] = self.scale_factors[i-1]*self.scale_factor
            self.level_sigmas2[i] = self.scale_factors[i]*self.scale_factors[i]*self.level_sigmas2[0]  
            self.level_sigmas[i]  = math.sqrt(self.level_sigmas2[i])        
        for i in range(num_levels):
            self.inv_scale_factors[i] = 1.0/self.scale_factors[i]
            self.inv_level_sigmas2[i] = 1.0/self.level_sigmas2[i]
        #print('self.scale_factor: ', self.scale_factor)                      
        #print('self.scale_factors: ', self.scale_factors)
        #print('self.level_sigmas: ', self.level_sigmas)                
        #print('self.inv_scale_factors: ', self.inv_scale_factors)          
        
        
    # initialize scale factors, sigmas for each octave level; 
    # these are used for managing image pyramids and weighting (information matrix) reprojection error terms in the optimization;
    # this method can be used only when the following mapping is adopted for SIFT:  
    #   keypoint.octave = (unpacked_octave+1)*3+unpacked_layer  where S=3 is the number of levels per octave
    def init_sigma_levels_sift(self): 
        print('initializing SIFT sigma levels')
        print('num_levels: ', self.num_levels)          
        self.num_levels = 3*self.num_levels + 3   # we map: level=keypoint.octave = (unpacked_octave+1)*3+unpacked_layer  where S=3 is the number of scales per octave
        num_levels = max(kNumLevelsInitSigma, self.num_levels) 
        #print('num_levels: ', num_levels) 
        # N.B: if we adopt the mapping: keypoint.octave = (unpacked_octave+1)*3+unpacked_layer 
        # then we can consider a new virtual scale_factor = 2^(1/3) (used between two contiguous layers of the same octave)
        print('original scale factor: ', self.scale_factor)
        self.scale_factor = math.pow(2,1./3)    
        self.inv_scale_factor = 1./self.scale_factor      
        self.scale_factors = np.zeros(num_levels)
        self.level_sigmas2 = np.zeros(num_levels)
        self.level_sigmas = np.zeros(num_levels)                
        self.inv_scale_factors = np.zeros(num_levels)
        self.inv_level_sigmas2 = np.zeros(num_levels)
        self.log_scale_factor = math.log(self.scale_factor)
        
        self.sigma_level0 = 1.6 # https://github.com/opencv/opencv/blob/173442bb2ecd527f1884d96d7327bff293f0c65a/modules/nonfree/src/sift.cpp#L118
                                # from https://docs.opencv.org/3.1.0/da/df5/tutorial_py_sift_intro.html 
        sigma_level02 = self.sigma_level0*self.sigma_level0        
        
        # N.B.: these are used only when recursive filtering is applied: see https://www.vlfeat.org/api/sift.html#sift-tech-ss
        #sift_init_sigma = 0.5    
        #sift_init_sigma2 = 0.25

        # see also https://www.vlfeat.org/api/sift.html
        self.scale_factors[0] = 1.0   
        self.level_sigmas2[0] = sigma_level02 # -4*sift_init_sigma2  N.B.: this is an absolute sigma, 
                                              # not a delta_sigma used for incrementally filtering contiguos layers => we must not subtract (4*sift_init_sigma2)   
                                              # https://github.com/opencv/opencv/blob/173442bb2ecd527f1884d96d7327bff293f0c65a/modules/nonfree/src/sift.cpp#L197
        self.level_sigmas[0] = math.sqrt(self.level_sigmas2[0])
        for i in range(1,num_levels):
            self.scale_factors[i] = self.scale_factors[i-1]*self.scale_factor
            self.level_sigmas2[i] = self.scale_factors[i]*self.scale_factors[i]*sigma_level02   # https://github.com/opencv/opencv/blob/173442bb2ecd527f1884d96d7327bff293f0c65a/modules/nonfree/src/sift.cpp#L224
            self.level_sigmas[i]  = math.sqrt(self.level_sigmas2[i])         
        for i in range(num_levels):
            self.inv_scale_factors[i] = 1.0/self.scale_factors[i]
            self.inv_level_sigmas2[i] = 1.0/self.level_sigmas2[i]
        #print('self.scale_factor: ', self.scale_factor)                      
        #print('self.scale_factors: ', self.scale_factors)
        #print('self.level_sigmas: ', self.level_sigmas)                
        #print('self.inv_scale_factors: ', self.inv_scale_factors)
             

    def rescale_keypoint_size(self, kps):
        # if keypoints are FAST, etc. then rescale their small sizes 
        # in order to let descriptors compute an encoded representation with a decent patch size    
        scale = 1   
        doit = False
        if doit: 
            for kp in kps:
                kp.size *= scale     
                             

    # detect keypoints without computing their descriptors
    # out: kps (array of cv2.KeyPoint)
    def detect(self, frame, mask=None):
        if not self.need_color_image and frame.ndim>2:                                    # check if we have to convert to gray image 
            frame = cv2.cvtColor(frame,cv2.COLOR_RGB2GRAY)                    
        if self.use_pyramid_adaptor:  
            # detection with pyramid adaptor (it can optionally include a block adaptor per level)
            kps = self.pyramid_adaptor.detect(frame, mask)            
        elif self.use_bock_adaptor:   
            # detection with block adaptor 
            kps = self.block_adaptor.detect(frame, mask)            
        else:                         
            # standard detection      
            kps = self._feature_detector.detect(frame, mask)  
        # filter keypoints    
        filter_name = 'NONE'
        # if keypoints are FAST, etc. give them a decent size in order to properly compute the descriptors       
        if self.do_keypoints_size_rescaling:
            self.rescale_keypoint_size(kps)             
        if kDrawOriginalExtractedFeatures: # draw the original features
            imgDraw = cv2.drawKeypoints(frame, kps, None, color=(0,255,0), flags=0)
            cv2.imshow('detected keypoints',imgDraw)            
        if kVerbose:
            print('detector:',self.detector_type.name,', #features:', len(kps),', [kp-filter:',filter_name,']')    
        return kps        
    
    
    # compute the descriptors once given the keypoints 
    def compute(self, frame, kps):
        if not self.need_color_image and frame.ndim>2:     # check if we have to convert to gray image 
            frame = cv2.cvtColor(frame,cv2.COLOR_RGB2GRAY)          
        kps, des = self._feature_descriptor.compute(frame, kps)  # then, compute descriptors 
        # filter keypoints     
        filter_name = 'NONE'
        if kVerbose:
            print('descriptor:',self.descriptor_type.name,', #features:', len(kps),', [kp-filter:',filter_name,']')           
        return kps, des 


    # detect keypoints and their descriptors
    # out: kps, des 
    def detectAndCompute(self, frame, mask=None):
        if not self.need_color_image and frame.ndim>2:     # check if we have to convert to gray image 
            frame = cv2.cvtColor(frame,cv2.COLOR_RGB2GRAY)  
        if self.use_pyramid_adaptor:  
            # detectAndCompute with pyramid adaptor (it can optionally include a block adaptor per level)
            if self.force_multiscale_detect_and_compute: 
                # force detectAndCompute on each level instead of first {detect() on each level} and then {compute() on resulting detected keypoints one time}
                kps, des = self.pyramid_adaptor.detectAndCompute(frame, mask)  
            #
            else: 
                kps = self.detect(frame, mask)        # first, detect by using adaptor on the different pyramid levels
                kps, des = self.compute(frame, kps)  # then, separately compute the descriptors on detected keypoints (one time)
        elif self.use_bock_adaptor:
            # detectAndCompute with block adaptor (force detect/compute on each block)
            #
            #kps, des = self.block_adaptor.detectAndCompute(frame, mask)    
            #
            kps = self.detect(frame, mask)        # first, detect by using adaptor
            kps, des = self.compute(frame, kps)  # then, separately compute the descriptors
        else:
            # standard detectAndCompute  
            if self.is_detector_equal_to_descriptor:                     
                # detector = descriptor => call them together with detectAndCompute() method    
                kps, des = self._feature_detector.detectAndCompute(frame, mask)   
                if kVerbose:
                    print('detector:', self.detector_type.name,', #features:',len(kps))           
                    print('descriptor:', self.descriptor_type.name,', #features:',len(kps))                      
            else:
                # detector and descriptor are different => call them separately 
                # 1. first, detect keypoint locations  
                kps = self.detect(frame, mask)
                # 2. then, compute descriptors           
                kps, des = self._feature_descriptor.compute(frame, kps)  
                if kVerbose:
                    #print('detector: ', self.detector_type.name, ', #features: ', len(kps))           
                    print('descriptor: ', self.descriptor_type.name, ', #features: ', len(kps))   
        # filter keypoints   
        filter_name = 'NONE'
        if kVerbose:
            print('detector:',self.detector_type.name,', descriptor:', self.descriptor_type.name,', #features:', len(kps),' (#ref:', self.num_features, '), [kp-filter:',filter_name,']')                                         
        self.debug_print(kps)             
        return kps, des             
 
 
    def debug_print(self, kps): 
        if False: 
            # raw print of all keypoints 
            for k in kps:
                print("response: ", k.response, "\t, size: ", k.size, "\t, octave: ", k.octave, "\t, angle: ", k.angle)
        if False: 
            # generate a rough histogram for keypoint sizes 
            kps_sizes = [kp.size for kp in kps] 
            kps_sizes_histogram = np.histogram(kps_sizes, bins=10)
            print('size-histogram: \n', list(zip(kps_sizes_histogram[1],kps_sizes_histogram[0])))            
        if False: 
            # count points for each octave => generate an octave histogram 
            kps_octaves = [k.octave for k in kps]
            kps_octaves = Counter(kps_octaves)
            print('levels-histogram: ', kps_octaves.most_common(12))    
                    