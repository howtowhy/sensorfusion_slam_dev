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

from enum import Enum
import cv2 


'''
NOTES: 
In order to add a new DETECTOR:
- add a new enum in FeatureDetectorTypes
- manage its 'case' in the detector inialization in feature_manager.py 

In order to add a new DESCRIPTOR:
- add a new enum in FeatureDescriptorTypes
- add the related information in the class FeatureInfo below
- manage its 'case' in the descriptor inialization in feature_manager.py 
'''

class FeatureDetectorTypes(Enum):   
    NONE = 0
    ORB2 = 1   # interface for ORB-SLAM2 features (ORB + spatial keypoint filtering)


class FeatureDescriptorTypes(Enum):
    NONE = 0   # used for LK tracker (in main_vo.py)
    ORB2 = 1   # [binary] interface for ORBSLAM2 features
    
    
class FeatureInfo(object): 
    norm_type = dict() 
    max_descriptor_distance = dict()   # initial reference max descriptor distances used by SLAM for locally searching matches around frame keypoints; 
                                       # these are initialized and then updated by using standard deviation robust estimation (MAD) and exponential smoothing 
                                       # N.B.: these intial reference distances can be easily estimated by using test_feature_matching.py 
                                       #       where (3 x sigma_mad) is computed 
    # 
    norm_type[FeatureDescriptorTypes.NONE] = cv2.NORM_L2
    max_descriptor_distance[FeatureDescriptorTypes.NONE] = float('inf')
    #
    norm_type[FeatureDescriptorTypes.ORB2] = cv2.NORM_HAMMING  
    max_descriptor_distance[FeatureDescriptorTypes.ORB2] = 100          # ORB