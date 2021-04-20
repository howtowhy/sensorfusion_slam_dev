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

from feature_tracker import FeatureTrackerTypes
from feature_types import FeatureDetectorTypes, FeatureDescriptorTypes
from parameters import Parameters


class FeatureTrackerConfigs(object):   
    
    # Test/Template configuration: you can use this to quickly test 
    # - your custom parameters and 
    # - favourite descriptor and detector (check the file feature_types.py)
    TEST = dict(
        num_features=Parameters.kNumFeatures,                   
        num_levels=8,                                  # N.B: some detectors/descriptors do not allow to set num_levels or they set it on their own
        scale_factor=1.2,                              # N.B: some detectors/descriptors do not allow to set scale_factor or they set it on their own
        detector_type=FeatureDetectorTypes.ORB2,
        descriptor_type=FeatureDescriptorTypes.ORB2,
        match_ratio_test=Parameters.kFeatureMatchRatioTest,
        tracker_type=FeatureTrackerTypes.DES_BF        # default descriptor-based, brute force matching with knn
    )