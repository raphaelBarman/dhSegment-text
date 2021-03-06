from tensorflow.contrib import slim, layers
import tensorflow as tf
from ...model import Encoder
import os
import tarfile
from ....utils.misc import get_data_folder, download_file
from ..vgg16 import mean_substraction
from .resnet_v1 import resnet_arg_scope, bottleneck, resnet_v1_block, resnet_v1
from .resnet_utils import Block
from ....embeddings.encoder import EmbeddingsEncoder
from typing import Type


class ResnetV1_50(Encoder):
    """ResNet-50 implementation

    :ivar train_batchnorm: Option to use batch norm
    :ivar blocks: number of blocks (resnet blocks)
    :ivar weight_decay: value of weight decay
    :ivar batch_renorm: Option to use batch renorm
    :ivar corrected_version: option to use the original resnet implementation (True) but less efficient than \
    `slim`'s implementation
    :ivar pretrained_file: path to the file (.ckpt) containing the pretrained weights
    """
    def __init__(self, train_batchnorm: bool=False, blocks: int=4, weight_decay: float=0.0001,
                 batch_renorm: bool=False, corrected_version: bool=False,
                 concat_level: int=-1, use_pretraining: bool=True):
        self.train_batchnorm = train_batchnorm
        self.blocks = blocks
        self.weight_decay = weight_decay
        self.batch_renorm = batch_renorm
        self.corrected_version = corrected_version
        self.concat_level = concat_level
        self.use_pretraining = use_pretraining
        self.pretrained_file = os.path.join(get_data_folder(), 'resnet_v1_50.ckpt')
        if not os.path.exists(self.pretrained_file):
            print("Could not find pre-trained file {}, downloading it!".format(self.pretrained_file))
            tar_filename = os.path.join(get_data_folder(), 'resnet_v1_50.tar.gz')
            download_file('http://download.tensorflow.org/models/resnet_v1_50_2016_08_28.tar.gz', tar_filename)
            tar = tarfile.open(tar_filename)
            tar.extractall(path=get_data_folder())
            tar.close()
            os.remove(tar_filename)
            assert os.path.exists(self.pretrained_file)
            print('Pre-trained weights downloaded!')

    def pretrained_information(self):
        if self.use_pretraining:
            if self.concat_level == -1:
                additional_variable = 'randomstring'
                additional_variable2 = 'randomstring'
            elif self.concat_level == 100:
                additional_variable = 'resnet_v1_50/conv1'
                additional_variable2 = 'randomstring'
            else:
                additional_variable = f"resnet_v1_50/block{self.concat_level+1}/unit_1/bottleneck_v1/conv1"
                additional_variable2 = f"resnet_v1_50/block{self.concat_level+1}/unit_1/bottleneck_v1/shortcut"
            return self.pretrained_file, [v for v in tf.global_variables()
                                          if 'resnet_v1_50' in v.name
                                          and 'renorm' not in v.name
                                          and 'group_norm' not in v.name
                                          and 'Embeddings' not in v.name
                                          and additional_variable not in v.name
                                          and additional_variable2 not in v.name]
        else:
            return None, None
        #return self.pretrained_file, [v for v in tf.global_variables()
        #                              if 'resnet_v1_50' in v.name]


    def __call__(self, images: tf.Tensor, is_training=False,
                 embeddings_encoder: Type[EmbeddingsEncoder]=None,
                 embeddings: tf.Tensor=tf.zeros((1,300), dtype=tf.float32),
                 embeddings_map: tf.Tensor=tf.zeros((200,200), dtype=tf.int32)):
        outputs = []

        with slim.arg_scope(resnet_arg_scope(weight_decay=self.weight_decay, batch_norm_decay=0.999)), \
             slim.arg_scope([layers.batch_norm], renorm_decay=0.95, renorm=self.batch_renorm):
            mean_substracted_tensor = mean_substraction(images)
            if self.concat_level == 100:
                with tf.variable_scope('Embeddings'):
                    embeddings_features = embeddings_encoder(embeddings, embeddings_map, tf.shape(mean_substracted_tensor)[1:3], is_training)
                    in_tensor = tf.concat([mean_substracted_tensor, embeddings_features], axis=-1)
            else:
                in_tensor = mean_substracted_tensor

            assert 0 < self.blocks <= 4

            if self.corrected_version:
                def corrected_resnet_v1_block(scope: str, base_depth: int, num_units: int, stride: int) -> tf.Tensor:
                    """
                    Helper function for creating a resnet_v1 bottleneck block.

                    :param scope: The scope of the block.
                    :param base_depth: The depth of the bottleneck layer for each unit.
                    :param num_units: The number of units in the block.
                    :param stride: The stride of the block, implemented as a stride in the last unit.
                                   All other units have stride=1.
                    :return: A resnet_v1 bottleneck block.
                    """
                    return Block(scope, bottleneck, [{
                        'depth': base_depth * 4,
                        'depth_bottleneck': base_depth,
                        'stride': stride
                    }] + [{
                        'depth': base_depth * 4,
                        'depth_bottleneck': base_depth,
                        'stride': 1
                    }] * (num_units - 1))

                blocks_list = [
                    corrected_resnet_v1_block('block1', base_depth=64, num_units=3, stride=1),
                    corrected_resnet_v1_block('block2', base_depth=128, num_units=4, stride=2),
                    corrected_resnet_v1_block('block3', base_depth=256, num_units=6, stride=2),
                    corrected_resnet_v1_block('block4', base_depth=512, num_units=3, stride=2),
                ]
                desired_endpoints = [
                    'resnet_v1_50/conv1',
                    'resnet_v1_50/block1/unit_3/bottleneck_v1',
                    'resnet_v1_50/block2/unit_4/bottleneck_v1',
                    'resnet_v1_50/block3/unit_6/bottleneck_v1',
                    'resnet_v1_50/block4/unit_3/bottleneck_v1'
                ]
            else:
                blocks_list = [
                    resnet_v1_block('block1', base_depth=64, num_units=3, stride=2),
                    resnet_v1_block('block2', base_depth=128, num_units=4, stride=2),
                    resnet_v1_block('block3', base_depth=256, num_units=6, stride=2),
                    resnet_v1_block('block4', base_depth=512, num_units=3, stride=1),
                ]
                desired_endpoints = [
                    'resnet_v1_50/conv1',
                    'resnet_v1_50/block1/unit_2/bottleneck_v1',
                    'resnet_v1_50/block2/unit_3/bottleneck_v1',
                    'resnet_v1_50/block3/unit_5/bottleneck_v1',
                    'resnet_v1_50/block4/unit_3/bottleneck_v1'
                ]
            net, endpoints = resnet_v1(in_tensor,
                                       blocks=blocks_list[:self.blocks],
                                       embeddings_encoder=embeddings_encoder,
                                       embeddings=embeddings,
                                       embeddings_map=embeddings_map,
                                       concat_level=self.concat_level,
                                       num_classes=None,
                                       #is_training=self.train_batchnorm and is_training,
                                       is_training=is_training,
                                       global_pool=False,
                                       output_stride=None,
                                       include_root_block=True,
                                       reuse=None,
                                       scope='resnet_v1_50')

            # Add standardized original images
            if self.concat_level != 100:
                outputs.append(mean_substracted_tensor/127.0)
            else:
                outputs.append(tf.concat([mean_substracted_tensor/127.0, embeddings_features], axis=-1))

            for d in desired_endpoints[:self.blocks + 1]:
                outputs.append(endpoints[d])

            return outputs
