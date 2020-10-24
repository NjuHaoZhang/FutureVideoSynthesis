### Copyright (C) 2017 NVIDIA Corporation. All rights reserved. 
### Licensed under the CC BY-NC-SA 4.0 license (https://creativecommons.org/licenses/by-nc-sa/4.0/legalcode).
import os.path
import random
import torch
from data.base_dataset import BaseDataset, get_img_params, get_transform
from PIL import Image
import numpy as np
from torch.autograd import Variable
#import sys
#sys.path.append("../OpticalFlowToolkit/lib/")
#import flowlib as fl
import cv2
import glob
def compute_bbox(mask):
    '''
    :param mask: mask of size(height, width)
    :return: bbox
    '''
    y, x  = np.where(mask == 1)
    if len(x) == 0 or len(y) == 0:
        return None
    bbox = np.zeros((2,2))
    bbox[:,0] = [np.min(x),np.min(y)]
    bbox[:,1] = [np.max(x),np.max(y)]
    return bbox




class TestTemporalDataset(BaseDataset):
    # Load pre-computed optical flow to save gpu memory
    def initialize(self, opt, flownet):
        self.opt = opt
        if opt.dataset == 'cityscapes':
            self.height = 512
            self.width  = 1024
        else:
            self.height = 256
            self.width = 832
        self.phase = 'val'
        self.flownet = flownet
        self.tIn = opt.tIn
        self.tOut = opt.tOut
        self.dataset = opt.dataset
        self.all_image_paths = self.load_all_image_paths(opt.npy_dir)
        self.n_of_seqs = len(self.all_image_paths)                 # number of sequences to train
        print("Testing number of video paths = %d"%self.n_of_seqs)
        self.use_test_back = False

    def __getitem__(self, index):
        cnt_info = np.load(self.all_image_paths[index], allow_pickle=True)
        tIn = self.opt.tIn
        tOut = self.opt.tOut
        n_gpu = len(self.opt.gpu_ids)
        tAll = tIn + tOut
        #print(self.all_image_paths[index])
        image_paths = cnt_info[0]
        #print("image paths", image_paths)
        semantic_paths = cnt_info[1]
        back_paths = cnt_info[2]
        depth_paths = cnt_info[3]
        dynamic_paths = cnt_info[4]
        instance_list = cnt_info[5]
        videoid = cnt_info[6]
        #print("video id", videoid)
        params = get_img_params(self.opt, (self.width, self.height))
        t_bic = get_transform(self.opt, params)
        t_ner = get_transform(self.opt, params, Image.NEAREST, normalize=False)

        Images = torch.cat([self.get_image(image_paths[p], t_bic) for p in range(tIn)], dim=0)
        Semantics = torch.cat([self.get_image(semantic_paths[p], t_ner, is_label=True) for p in range(tIn)], dim=0)
        Backs = torch.cat([self.get_image(back_paths[p], t_bic) for p in range(tIn+tOut)], dim=0)
        Depths = torch.cat([torch.from_numpy(np.expand_dims(np.load(depth_paths[p]), axis=0)) for p in range(tIn)], dim=0)
        # Load Necessary information for all objects and transform to tensor
        Combines = 0
        back_list = []
        image_list = []
        dynamic_list = []
        for i in range(tIn):
            back_path = back_paths[i]
            back = np.array(Image.open(back_path))
            #print("back", back.shape)#
            back_list.append(back)
            image_path = image_paths[i]
            image = np.array(Image.open(image_path).resize((self.width, self.height), resample=Image.BILINEAR))
            #print("image shape", image.shape)
            image_list.append(image)
            dynamic_path = dynamic_paths[i]
            #if self.dataset == 'cityscapes':
            #    dynamic_mask = np.array(Image.open(dynamic_path).resize((self.width, self.height), resample=Image.NEAREST))/255
            #else:
            dynamic_mask = np.array(Image.open(dynamic_path))/255
            dynamic_list.append(dynamic_mask)

        Masks = 0
        Combines = 0
        LastObjects = 0
        LastMasks = 0
        Classes = 0
        for k in range(len(instance_list)):
            frames = instance_list[k][0]
            H = 512 if self.dataset == 'cityscapes' else 256
            if len(frames) == H:
                frames = [frames]
            if self.dataset == 'kitti':
                frames = self.update_frames(frames)
            cl = instance_list[k][1]
            cnt_mask_seq, cnt_combine_seq, cnt_last_object, cnt_last_mask = self.gen_combine_seq(frames, image_list, back_list, t_ner, t_bic)                     
            Masks = cnt_mask_seq if Masks is 0 else torch.cat([Masks, cnt_mask_seq], dim=0)
            Combines = cnt_combine_seq if Combines is 0 else torch.cat([Combines, cnt_combine_seq], dim=0)
            LastObjects = cnt_last_object if LastObjects is 0 else torch.cat([LastObjects, cnt_last_object], dim=0)
            cnt_class = torch.from_numpy(np.array([cl]))
            Classes = cnt_class if Classes is 0 else torch.cat([Classes, cnt_class], dim = 0)
            LastMasks = cnt_last_mask if LastMasks is 0 else torch.cat([LastMasks, cnt_last_mask], dim=0)


        return_list = {'Image': Images,'Back': Backs, 'Mask': Masks, 'Semantic': Semantics, \
            'Combine': Combines, 'LastObject': LastObjects, 'Depths': Depths, 'Classes': Classes, 'LastMasks': LastMasks, 'VideoId': videoid}
        return return_list


    def update_frames(self, frames):
        new_frames = []
        for p in frames:
            p = np.array(Image.fromarray(p).resize((self.width, self.height), resample=Image.BILINEAR))
            new_frames.append(p)
        return new_frames
    
    def gen_combine_seq(self, masks_seq, image_list, back_list, t_ner, t_bic):
        if len(masks_seq) == 1:
            # tracker faied, use flow warp
            cnt_mask_seq = self.warp_mask_seq(masks_seq, image_list)

        else:
            # tracker success
            cnt_mask_seq = masks_seq
        combine_list = []
        for i in range(self.tIn):
            tmp_mask = np.tile(np.expand_dims(cnt_mask_seq[i], axis=2), [1,1,3])
            #print("image shape", image_list[i].shape)
            #print("tmp mask", tmp_mask.shape)
            #print("back mask", back_list[i].shape)
            cnt_combine = image_list[i]*tmp_mask + back_list[i]*(1.0 - tmp_mask)
            combine_list.append(cnt_combine)
        # transform masks and images to tensors
        cnt_Masks = 0
        cnt_Combines = 0
        #print("len cnt mask", len(cnt_mask_seq))
        for i in range(self.tIn):
            cnt_Maski = t_ner(Image.fromarray(cnt_mask_seq[i].astype(np.uint8)))#0-1->0-1/255
            cnt_Maski *= 255
            cnt_Combinei = t_bic(Image.fromarray(combine_list[i].astype(np.uint8)))
            cnt_Masks = cnt_Maski if i == 0 else torch.cat([cnt_Masks, cnt_Maski], dim=0)
            cnt_Combines = cnt_Combinei if i == 0 else torch.cat([cnt_Combines, cnt_Combinei], dim=0)
        last_image = image_list[-1]
        last_mask = cnt_mask_seq[-1]
        kernel_1 = np.ones((9,9), np.uint8)
        last_mask_1 = cv2.dilate(last_mask.astype(np.float32), kernel_1, iterations=1)
        last_object = last_image * np.tile(np.expand_dims(last_mask_1, axis=2), [1,1,3])
        LastObject = t_bic(Image.fromarray(last_object.astype(np.uint8)))
        kernel_2 = np.ones((7,7), np.uint8)
        last_mask_2 = cv2.dilate(last_mask.astype(np.float32), kernel_2, iterations=1)
        LastMask = t_ner(Image.fromarray(last_mask_2.astype(np.uint8)))
        LastMask *= 255
        return cnt_Masks, cnt_Combines, LastObject, LastMask


    def warp_mask_seq(self, mask_seq, image_list):
        last_mask = mask_seq[0]
        #print("last_mask shape=", last_mask.shape)
        with torch.no_grad():
            last_mask_ = np.expand_dims(np.expand_dims(last_mask, axis=0), axis=0)
            #print("last_mask_", last_mask_.shape)
            last_mask_tensor = torch.from_numpy(last_mask_)
            last_mask_tensor = torch.autograd.Variable(last_mask_tensor.cuda(self.opt.gpu_ids[0]).float(), volatile=True)#
            mask_list = []
            for i in range(self.tIn - 1):
                image_a = image_list[i]
                image_b = image_list[-1]
                image_a = image_a / 127.5 - 1
                image_b = image_b / 127.5 - 1
                image_a = np.expand_dims(np.transpose(image_a, [2,0,1]), axis=0)
                image_b = np.expand_dims(np.transpose(image_b, [2,0,1]), axis=0)
                image_a_tensor = torch.from_numpy(image_a)
                image_b_tensor = torch.from_numpy(image_b)
                image_a_tensor = torch.autograd.Variable(image_a_tensor.cuda(self.opt.gpu_ids[0]).float(), volatile=True)#
                image_b_tensor = torch.autograd.Variable(image_b_tensor.cuda(self.opt.gpu_ids[0]).float(), volatile=True)#
                flow_a_b, conf_a_b = self.flownet(image_a_tensor, image_b_tensor)
                warp_mask = self.resample(last_mask_tensor, flow_a_b, 'nearest')
                warp_mask = warp_mask.cpu().data.numpy()
                #print("warp_mask shape", warp_mask.shape)
                #warp_mask = self.clip_mask(warp_mask)
                mask_list.append(warp_mask[0,0,...])
            mask_list.append(last_mask)
        return mask_list

    def whether_move(self, frames):
        if len(frames) == 4:
            c_x_list = [None]*4
            c_y_list = [None]*4
            diff_c_x = [None]*3
            diff_c_y = [None]*3
            for k in range(4):
                cnt_mask = frames[k]
                c_x, c_y = self.mask2bbox(cnt_mask)
                c_x_list[k] = c_x
                c_y_list[k] = c_y
            for k in range(3):
                diff_c_x[k] = np.abs(c_x_list[k+1] - c_x_list[k])
                diff_c_y[k] = np.abs(c_y_list[k+1] - c_y_list[k])
            if np.maximum(np.array(diff_c_x).max(), np.array(diff_c_y).max()) < 5:
                return False
        return True

    def mask2bbox(self, mask):
        y, x = np.where(mask == 1)
        min_y = np.min(y)
        max_y = np.max(y)
        min_x = np.min(x)
        max_x = np.max(x)
        center_x = min_x + (max_x - min_x)/2.0
        center_y = min_y + (max_y - min_y)/2.0
        return center_x, center_y

    def get_image(self, A_path, transform_scaleA, is_label=False):
        #print(A_path)
        A_img = Image.open(A_path)
        A_scaled = transform_scaleA(A_img)
        if is_label:
            A_scaled *= 255
        return A_scaled

    def __len__(self):
        return self.n_of_seqs

    def name(self):
        return 'TestTemporalDataset'

    def load_all_image_paths(self, path):
        npy_files = sorted(glob.glob(path + "*.npy"))
        return npy_files
        
    def LoadDepthDataSample(self, DepthRoot, images):
        tmp = []
        for p in range(self.tIn):
            curr_full = images[p]
            split_name = curr_full.split("/")
            depth_path = os.path.join(DepthRoot, split_name[-3],split_name[-2],split_name[-1])
            depth_path = depth_path[:-3] + "npy"
            tmp.append(scipy.misc.imresize(np.load(depth_path),(self.h, self.w)))
        Depth = np.concatenate([np.expand_dims(np.expand_dims(tmp[q], 0), 3) for q in range(self.tIn)],axis=3)
        # Depth may be zero, compute average value then 1/average depth
        return Depth

    def IOU_mask(self, mask_A, mask_B):
        #semantic instance,
        mask_A = mask_A.astype(np.bool)
        mask_B = mask_B.astype(np.bool)
        return 1.0 * (mask_A & mask_B).astype(np.int32).sum() / mask_B.astype(np.int32).sum()


    def load_object_mask_val(self, instance_mask_list, images, depth):
        '''
        :param instance: instance contains gt instance or
        :param semantic:
        :param depth:
        :param curr_image:
        :param gt_flag:
        :return:
        '''
        opt = self.opt
        segs = []
        
        for j in range(len(instance_mask_list)):
            #print(instance_mask_list[j])
            cnt_info = []
            flag = True
            for k in range(self.tIn):
                cnt_mask = np.array(Image.open(instance_mask_list[j][k]).resize((self.sp*2, self.sp), resample=Image.NEAREST))/255
                cnt_mask_expand = expand_dims_2(cnt_mask)
                cnt_bbox = compute_bbox(cnt_mask)
                if cnt_bbox is None:
                    continue
                big_bbox = self.enlarge_bbox(cnt_bbox)
                big_mask = self.bbox2mask(big_bbox)
                cnt_bbox_mask = self.bbox2mask(cnt_bbox)
                cnt_depth = np.mean(cnt_mask_expand * self.depthInput[:,:,:,k:k+1])
                cnt_color_image = np.tile(cnt_mask_expand, [1, 1, 1, 3]) * images[:,:,:,k*3:(k+1)*3]
                #scipy.misc.imsave("./debug/segs_%d.png" % j, cnt_color_image[0, :, :, :])
                big_image = np.tile(expand_dims_2(big_mask), [1, 1, 1, 3]) * images[:,:,:,k*3:(k+1)*3]
                cnt_info.append(
                        (cnt_mask, cnt_color_image[0, :, :, :], cnt_depth, cnt_bbox, big_image[0, :, :, :]))
            if len(cnt_info) > 0:
                segs.append(cnt_info)
        return segs


    def preprocess_bike_person(self, instance_list):
        valid_index = np.zeros(len(instance_list)) + 1
        # classes
        #'person'-1, 'bicycle'-2, 'car'-3, 'motorcycle'-4,'bus'-6, 'train'-7, 'truck'-8
        valid_class = [1,2,3,4,6,7,8]
        mask_all = []
        for i in range(len(instance_list)):
            if valid_index[i] == 0:
                continue
            curr_list = instance_list[i]
            if curr_list['class_id'] not in valid_class:
                continue
            if curr_list['class_id'] == 2 or curr_list['class_id'] == 4:
                iou_score = -1
                person_id = -1
                bbox_bike = curr_list['bbox']
                bbox_mask_bike = bbox2mask_maskrcnn(bbox_bike)
                for j in range(len(instance_list)):
                    if valid_index[j] == 1:
                        if instance_list[j]['class_id'] == 1:
                            bbox_person = instance_list[j]['bbox']
                            bbox_mask_person = bbox2mask_maskrcnn(bbox_person)
                            iou = self.IOU_mask(bbox_mask_bike, bbox_mask_person)
                            if iou > iou_score:
                                iou_score = iou
                                person_id = j
                if iou_score > 0:
                    mask_all.append(((curr_list['mask'] | instance_list[person_id]['mask']), 9))
                    valid_index[i] = 0
                    valid_index[person_id] = 0
        for k in range(len(instance_list)):
            if valid_index[k] == 1 and instance_list[k]['class_id'] in valid_class:
                mask_all.append((instance_list[k]['mask'], instance_list[k]['class_id']))
        return mask_all

    def enlarge_bbox(self, bbox):
        '''
        bbox[:, 0] = [np.min(x), np.min(y)]
        bbox[:, 1] = [np.max(x), np.max(y)]
        bbox [min_x, max_x]
             [min_y, max_y]
        '''
        # enlarge bbox to avoid any black boundary
        if self.opt.sp == 256:
            gap = 2
        elif self.opt.sp == 512:
            gap = 4
        elif self.opt.sp == 1024:
            gap = 8
        bbox[0,0] = np.maximum(bbox[0,0] - gap, 0)
        bbox[1,0] = np.maximum(bbox[1,0] - gap, 0)
        bbox[0,1] = np.minimum(bbox[0,1] + gap, self.w-1)
        bbox[1,1] = np.minimum(bbox[1,1] + gap, self.h-1)
        return bbox

    def bbox2mask(self, bbox):
        mask = np.zeros((self.h, self.w))
        bbox = bbox.astype(np.int32)
        mask[bbox[1,0]:bbox[1,1]+1,bbox[0,0]:bbox[0,1]+1] = 1
        return mask
