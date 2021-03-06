import argparse, os
import sys
sys.path.append(os.path.abspath(os.path.join(__file__, '..', '..')))
from shutil import copyfile
import cvbase as cvb
from PIL import Image
import numpy as np
from tools.frame_inpaint import DeepFillv1

# Test script
def parse_argse():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dataset_root', type=str,
                        default=None)
    # FlowNet2
    parser.add_argument('--FlowNet2', action='store_true')
    parser.add_argument('--pretrained_model_flownet2', type=str,
                        default='./pretrained_models/FlowNet2_checkpoint.pth.tar')
    parser.add_argument('--img_size', type=int, nargs='+',
                        default=None)
    parser.add_argument('--rgb_max', type=float, default=255.)
    parser.add_argument('--fp16', action='store_true')
    parser.add_argument('--data_list', type=str, default=None, help='Give the data list to extract flow')
    parser.add_argument('--frame_dir', type=str, default=None,
                        help='Give the dir of the video frames and generate the data list to extract flow')
    parser.add_argument('--PRINT_EVERY', type=int, default=50)

    # DFCNet
    parser.add_argument('--DFC', action='store_true')
    parser.add_argument('--ResNet101', action='store_true')
    parser.add_argument('--MS', action='store_true')
    parser.add_argument('--batch_size', type=int, default=1)
    parser.add_argument('--n_threads', type=int, default=16)

    parser.add_argument('--get_mask', action='store_true')
    parser.add_argument('--output_root', type=str,
                        default=None)

    parser.add_argument('--DATA_ROOT', type=str,
                        default=None)
    parser.add_argument('--MASK_ROOT', type=str, default=None)

    parser.add_argument('--MASK_MODE', type=str, default=None)
    parser.add_argument('--SAVE_FLOW', action='store_true')
    parser.add_argument('--IMAGE_SHAPE', type=int, default=[240, 424], nargs='+')
    parser.add_argument('--RES_SHAPE', type=int, default=[240, 424], nargs='+')

    parser.add_argument('--PRETRAINED_MODEL', type=str, default=None)
    parser.add_argument('--PRETRAINED_MODEL_1', type=str,
                        default='./pretrained_models/resnet101_movie.pth')
    parser.add_argument('--PRETRAINED_MODEL_2', type=str,
                        default=None)
    parser.add_argument('--PRETRAINED_MODEL_3', type=str,
                        default=None)
    parser.add_argument('--INITIAL_HOLE', action='store_true')
    parser.add_argument('--EVAL_LIST', type=str,
                        default=None)
    parser.add_argument('--enlarge_mask', action='store_true')
    parser.add_argument('--enlarge_kernel', type=int,
                        default=3)

    # Flow-Guided Propagation
    parser.add_argument('--Propagation', action='store_true')
    parser.add_argument('--img_shape', type=int, nargs='+', default=[480, 840],
                        help='if img_shape[0] is 0, keep the original solution of the video')
    parser.add_argument('--th_warp', type=int, default=40)
    parser.add_argument('--img_root', type=str,
                        default=None)
    parser.add_argument('--mask_root', type=str,
                        default=None)
    parser.add_argument('--flow_root', type=str,
                        default=None)
    parser.add_argument('--output_root_propagation', type=str,
                        default=None)
    parser.add_argument('--pretrained_model_inpaint', type=str,
                        default='./pretrained_models/imagenet_deepfill.pth')

    args = parser.parse_args()

    return args


def extract_flow(args):
    from tools.infer_flownet2 import infer
    output_file = infer(args)
    flow_list = [x for x in os.listdir(output_file) if '.flo' in x]
    flow_start_no = min([int(x[:5]) for x in flow_list])

    zero_flow = cvb.read_flow(os.path.join(output_file, flow_list[0]))
    cvb.write_flow(zero_flow*0, os.path.join(output_file, '%05d.rflo' % flow_start_no))
    args.DATA_ROOT = output_file


def flow_completion(args):

    data_list_dir = os.path.join(args.dataset_root, 'data')
    if not os.path.exists(data_list_dir):
        os.makedirs(data_list_dir)
    initial_data_list = os.path.join(data_list_dir, 'initial_test_list.txt')
    print('Generate datalist for initial step')

    from dataset.data_list import gen_flow_initial_test_mask_list
    gen_flow_initial_test_mask_list(flow_root=args.DATA_ROOT,
                                    output_txt_path=initial_data_list)
    args.EVAL_LIST = os.path.join(data_list_dir, 'initial_test_list.txt')

    from tools.test_scripts import test_initial_stage
    args.output_root = os.path.join(args.dataset_root, 'Flow_res', 'initial_res')
    args.PRETRAINED_MODEL = args.PRETRAINED_MODEL_1

    if args.img_size is not None:
        args.IMAGE_SHAPE = [args.img_size[0] // 2, args.img_size[1] // 2]
        args.RES_SHAPE = args.IMAGE_SHAPE

    print('Flow Completion in First Step')
    test_initial_stage(args)
    args.flow_root = args.output_root

    if args.MS:
        from tools.test_scripts import test_refine_stage
        args.PRETRAINED_MODEL = args.PRETRAINED_MODEL_2
        args.IMAGE_SHAPE = [320, 600]
        args.RES_SHAPE = [320, 600]
        args.DATA_ROOT = args.output_root
        args.output_root = os.path.join(args.dataset_root, 'Flow_res', 'stage2_res')

        stage2_data_list = os.path.join(data_list_dir, 'stage2_test_list.txt')
        from dataset.data_list import gen_flow_refine_test_mask_list
        gen_flow_refine_test_mask_list(flow_root=args.DATA_ROOT,
                                       output_txt_path=stage2_data_list)
        args.EVAL_LIST = stage2_data_list
        test_refine_stage(args)

        args.PRETRAINED_MODEL = args.PRETRAINED_MODEL_3
        args.IMAGE_SHAPE = [480, 840]
        args.RES_SHAPE = [480, 840]
        args.DATA_ROOT = args.output_root
        args.output_root = os.path.join(args.dataset_root, 'Flow_res', 'stage3_res')

        stage3_data_list = os.path.join(data_list_dir, 'stage3_test_list.txt')
        from dataset.data_list import gen_flow_refine_test_mask_list
        gen_flow_refine_test_mask_list(flow_root=args.DATA_ROOT,
                                       output_txt_path=stage3_data_list)
        args.EVAL_LIST = stage3_data_list
        test_refine_stage(args)
        args.flow_root = args.output_root


def flow_guided_propagation(args):

    deepfill_model = DeepFillv1(pretrained_model=args.pretrained_model_inpaint,
                                image_shape=args.img_shape)

    from tools.propagation_inpaint import propagation
    propagation(args,
                frame_inapint_model=deepfill_model)


def load_all_image_paths(image_root):
    train_set = []
    scene_dir = os.listdir(image_root)
    scene_dir.sort()
    for i in range(len(scene_dir)):
        image_dir = image_root + scene_dir[i] + "/image_02/data/"
        image_list = os.listdir(image_dir)
        image_list.sort()
        for k in range(len(image_list)- 8 ):
            images = []
            for f in range(k, k + 9):
                image_full_path = image_dir + image_list[f]
                assert os.path.isfile(image_full_path)
                images.append(image_full_path)
            train_set.append(images)
    return train_set


def main():
    root = "/disk2/yue/server6_backup/final/finetune_0.002_add_person/kitti/"
    #root = "./example/"
    val_root = "/disk1/yue/kitti/raw_data/val/"
    val_img_list = load_all_image_paths(val_root)
    assert len(val_img_list) == 1337
    args = parse_argse()
    print(len(val_img_list))
    for i in range(0, 1337):
        print("processing %03d"%i)
        sub_dir = root + "%04d/"%i
        img_list = []
        mask_list = []
        input_len = 4
        flag = True
        for j in range(5+input_len):
            if j < input_len:
                # 1 0 3
                # 2 0 2 1 3
                # 3 0 1 2 2 3 3
                # 4 0 0 1 1 2 2 3 3
                img_0 = val_img_list[i][j]
                copyfile(img_0, "./demo/frames/%05d.png"%j)
                mask = np.zeros((256, 832, 3))
                mask_ = Image.fromarray(mask.astype(np.uint8)).save("./demo/masks/%05d.png"%j)
            else:
                if os.path.exists(sub_dir + "fore_complete_%02d.png"%(j-input_len)):
                    copyfile(sub_dir + "fore_complete_%02d.png"%(j-input_len), "./demo/frames/%05d.png"%(j))
                else:
                    flag = False
                    break
                mask = np.array(Image.open(sub_dir + "occ_%02d.png"%(j-input_len)).convert('RGB'))
                mask = 255 - mask
                mask_ = Image.fromarray(mask).save("./demo/masks/%05d.png"%(j))
                if j % 3 == 0:
                    mask = np.array(Image.open(sub_dir + "occ_boundary_%02d.png"%(j-input_len)).convert('RGB'))
                    mask = 255 - mask
                    mask_ = Image.fromarray(mask.astype(np.uint8)).save("./demo/masks/%05d.png"%(j))
                if j == 5 + input_len - 1:
                    copyfile(sub_dir + "fore_complete_%02d.png"%(j-input_len), "./demo/frames/%05d.png"%(j+1))
                    mask = np.array(Image.open(sub_dir + "occ_boundary_%02d.png"%(j-input_len)).convert('RGB'))
                    mask = 255 - mask
                    mask_ = Image.fromarray(mask.astype(np.uint8)).save("./demo/masks/%05d.png"%(j+1))
        if flag == False:
            continue
        if args.frame_dir is not None:
            args.dataset_root = os.path.dirname(args.frame_dir)
        if args.FlowNet2:
            extract_flow(args)

        if args.DFC:
            flow_completion(args)

        # set propagation args
        assert args.mask_root is not None or args.MASK_ROOT is not None
        args.mask_root = args.MASK_ROOT if args.mask_root is None else args.mask_root
        args.img_root = args.frame_dir

        if args.output_root_propagation is None:
            args.output_root_propagation = os.path.join(args.dataset_root, 'Inpaint_Res')
        if args.img_size is not None:
            args.img_shape = args.img_size
        if args.Propagation:
            flow_guided_propagation(args)
        for j in range(input_len + 5):
            copyfile("./demo/Inpaint_Res/inpaint_res/%05d.png"%(j), sub_dir + "video_inpaint_%05d.png"%j)


if __name__ == '__main__':
    main()
