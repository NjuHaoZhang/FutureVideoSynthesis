CUDA_VISIBLE_DEVICES=1 python test_city_myback_next.py \
  --gpu_ids 0 \
  --batchSize 1 \
  --name city_car_final_test \
  --ngf 32 \
  --loadSize 1024 \
  --use_my_back \
  --next \
  --ImagesRoot "/disk1/yue/cityscapes/leftImg8bit_sequence_512p/" \
  --npy_dir "/disk2/yue/server6_backup/final/tracking/train_data_gen/generate_valid_train_list/test_2/" \
  --load_pretrain "./checkpoints/city_car_final/tmp/"
