"""icgan_colab.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/github/facebookresearch/ic_gan/blob/main/inference/icgan_colab.ipynb

Copyright (c) Facebook, Inc. and its affiliates.
All rights reserved.

This source code is licensed under the license found in the
LICENSE file in the root directory of this source tree.

# IC-GAN


Official Colab notebook from the paper <b>"Instance-Conditioned GAN"</b> by Arantxa Casanova, Marlene Careil, Jakob Verbeek, Michał Drożdżal, Adriana Romero-Soriano.

This Colab provides the code to generate images with IC-GAN, with the option of further guiding the generation with captions (CLIP). 

Based on the Colab [WanderClip](https://j.mp/wanderclip) by Eyal Gruss [@eyaler](https://twitter.com/eyaler) [eyalgruss.com](https://eyalgruss.com)

Using the work from [our repository](https://github.com/facebookresearch/ic_gan)

https://github.com/openai/CLIP, Copyright (c) 2021 OpenAI

https://github.com/huggingface/pytorch-pretrained-BigGAN, Copyright (c) 2019 Thomas Wolf
"""

# wget https://dl.fbaipublicfiles.com/ic_gan/cc_icgan_biggan_imagenet_res256.tar.gz
# tar -xvf cc_icgan_biggan_imagenet_res256.tar.gz
# wget https://dl.fbaipublicfiles.com/ic_gan/icgan_biggan_imagenet_res256.tar.gz
# tar -xvf icgan_biggan_imagenet_res256.tar.gz
# wget https://dl.fbaipublicfiles.com/ic_gan/stored_instances.tar.gz
# tar -xvf stored_instances.tar.gz
# curl -L -o swav_pretrained.pth.tar -C - 'https://dl.fbaipublicfiles.com/deepcluster/swav_800ep_pretrain.pth.tar'
# tar -xvf swav_pretrained.pth.tar

import os
import sys
import warnings
from glob import glob
from pathlib import Path

import cma
import cv2
import imageio
import nltk
import numpy as np
import torch
import torchvision.transforms as transforms
from nltk.corpus import wordnet as wn
from PIL import Image as Image_PIL
from pytorch_pretrained_biggan import utils
from scipy.stats import truncnorm
from torch import nn
from tqdm import tqdm

sys.path.append(os.path.dirname(__file__) + "/../submodules/ic_gan/stylegan2_ada_pytorch")
sys.path.append(os.path.dirname(__file__) + "/../submodules/ic_gan/inference")
sys.path.append(os.path.dirname(__file__) + "/../submodules/ic_gan")
sys.path.append(os.path.dirname(__file__) + "/../submodules/ic_gan")
sys.path.append(os.path.dirname(__file__) + "/../submodules/Real-ESRGAN")

import data_utils.utils as data_utils
import inference.utils as inference_utils
import realesrgan
import sklearn.metrics
from basicsr.archs.rrdbnet_arch import RRDBNet

warnings.simplefilter("ignore", cma.evolution_strategy.InjectionWarning)
nltk.download("wordnet")
torch.manual_seed(np.random.randint(sys.maxsize))
norm_mean = torch.Tensor([0.485, 0.456, 0.406]).view(3, 1, 1)
norm_std = torch.Tensor([0.229, 0.224, 0.225]).view(3, 1, 1)
hist = []


def replace_to_inplace_relu(
    model,
):  # saves memory; from https://github.com/minyoungg/pix2latent/blob/master/pix2latent/model/biggan.py
    for child_name, child in model.named_children():
        if isinstance(child, nn.ReLU):
            setattr(model, child_name, nn.ReLU(inplace=False))
        else:
            replace_to_inplace_relu(child)
    return


def load_icgan(experiment_name, root_="modelzoo/"):
    root = os.path.join(root_, experiment_name)
    config = torch.load("%s/%s.pth" % (root, "state_dict_best0"))["config"]

    config["weights_root"] = root_
    config["model_backbone"] = "biggan"
    config["experiment_name"] = experiment_name
    # TODO: delete this line
    G, config = inference_utils.load_model_inference(config)
    G.cuda()
    G.eval()
    return G


def get_output(noise_vector, input_label, input_features):
    if stochastic_truncation:  # https://arxiv.org/abs/1702.04782
        with torch.no_grad():
            trunc_indices = noise_vector.abs() > 2 * truncation
            size = torch.count_nonzero(trunc_indices).cpu().numpy()
            trunc = truncnorm.rvs(-2 * truncation, 2 * truncation, size=(1, size)).astype(np.float32)
            noise_vector.data[trunc_indices] = torch.tensor(trunc, requires_grad=False, device="cuda")
    else:
        noise_vector = noise_vector.clamp(-2 * truncation, 2 * truncation)
    if input_label is not None:
        input_label = torch.LongTensor(input_label)
    else:
        input_label = None

    out = model(
        noise_vector,
        input_label.cuda() if input_label is not None else None,
        input_features.cuda() if input_features is not None else None,
    )

    if channels == 1:
        out = out.mean(dim=1, keepdim=True)
        out = out.repeat(1, 3, 1, 1)
    return out


def normality_loss(vec):  # https://arxiv.org/abs/1903.00925
    mu2 = vec.mean().square()
    sigma2 = vec.var()
    return mu2 + sigma2 - torch.log(sigma2) - 1


def load_generative_model(gen_model, last_gen_model, experiment_name, model):
    # Load generative model
    if gen_model != last_gen_model:
        model = load_icgan(experiment_name, root_="modelzoo/")
        last_gen_model = gen_model
    return model, last_gen_model


def load_feature_extractor(gen_model, last_feature_extractor, feature_extractor):
    # Load feature extractor to obtain instance features
    feat_ext_name = "classification" if gen_model == "cc_icgan" else "selfsupervised"
    if last_feature_extractor != feat_ext_name:
        if feat_ext_name == "classification":
            feat_ext_path = ""
        else:
            feat_ext_path = "modelzoo/swav_pretrained.pth.tar"
        last_feature_extractor = feat_ext_name
        feature_extractor = data_utils.load_pretrained_feature_extractor(feat_ext_path, feature_extractor=feat_ext_name)
        feature_extractor.eval()
    return feature_extractor, last_feature_extractor


def preprocess_input_image(input_image_path, size):
    pil_image = Image_PIL.open(input_image_path).convert("RGB")
    transform_list = transforms.Compose(
        [
            data_utils.CenterCropLongEdge(),
            transforms.Resize((size, size)),
            transforms.ToTensor(),
            transforms.Normalize(norm_mean, norm_std),
        ]
    )
    tensor_image = transform_list(pil_image)
    tensor_image = torch.nn.functional.interpolate(tensor_image.unsqueeze(0), 224, mode="bicubic", align_corners=True)
    return tensor_image


def preprocess_generated_image(image):
    transform_list = transforms.Normalize(norm_mean, norm_std)
    image = transform_list(image * 0.5 + 0.5)
    image = torch.nn.functional.interpolate(image, 224, mode="bicubic", align_corners=True)
    return image


last_gen_model = None
last_feature_extractor = None
model = None
feature_extractor = None

# @title Generate images with IC-GAN!
# @markdown 1. Select type of IC-GAN model with **gen_model**: "icgan" is conditioned on an instance; "cc_icgan" is conditioned on both instance and a class index.
# @markdown 1. Select which instance to condition on, following one of the following options:
# @markdown     1. **input_image_instance** is the path to an input image, from either the mounted Google Drive or a manually uploaded image to "Files" (left part of the screen).
# @markdown     1. **input_feature_index** write an integer from 0 to 1000. This will change the instance conditioning and therefore the style and semantics of the generated images. This will select one of the 1000 instance features pre-selected from ImageNet using k-means.
# @markdown 1. For **class_index** (only valid for gen_model="cc_icgan") write an integer from 0 to 1000. This will change the ImageNet class to condition on. Consult [this link](https://gist.github.com/yrevar/942d3a0ac09ec9e5eb3a) for a correspondence between class name and indexes.
# @markdown 1. **num_samples_ranked** (default=16) indicates the number of generated images to output in a mosaic. These generated images are the ones that scored a higher cosine similarity with the conditioning instance, out of **num_samples_total** (default=160) generated samples. Increasing "num_samples_total" will result in higher run times, but more generated images to choose the top "num_samples_ranked" from, and therefore higher chance of better image quality. Reducing "num_samples_total" too much could result in generated images with poorer visual quality. A ratio of 10:1 (num_samples_total:num_samples_ranked) is recommended.
# @markdown 1. Vary **truncation** (default=0.7) from 0 to 1 to apply the [truncation trick](https://arxiv.org/abs/1809.11096). Truncation=1 will provide more diverse but possibly poorer quality images. Trucation values between 0.7 and 0.9 seem to empirically work well.
# @markdown 1. **seed**=0 means no seed.

gen_model = "icgan"  # @param ['icgan', 'cc_icgan']
if gen_model == "icgan":
    experiment_name = "icgan_biggan_imagenet_res256"
else:
    experiment_name = "cc_icgan_biggan_imagenet_res256"
# last_gen_model = experiment_name
size = "256"
input_image_instance = "/home/hans/datasets/diffuse/select/Dystopian_metropolis_trending_on_ArtStation_2418853.png"  # @param {type:"string"}
input_feature_index = 3  # @param {type:'integer'}
class_index = 538  # @param {type:'integer'}
num_samples_ranked = 8  # @param {type:'integer'}
num_samples_total = 240  # @param {type:'integer'}
truncation = 1.0  # @param {type:'number'}
stochastic_truncation = True  # @param {type:'boolean'}
download_file = False  # @param {type:'boolean'}
seed = None
noise_size = 128
class_size = 1000
channels = 3
batch_size = 4
if gen_model == "icgan":
    class_index = None
if "biggan" in gen_model:
    input_feature_index = None
    input_image_instance = None

assert num_samples_ranked <= num_samples_total

state = None if not seed else np.random.RandomState(seed)
np.random.seed(seed)

feature_extractor_name = "classification" if gen_model == "cc_icgan" else "selfsupervised"
# Load feature extractor (outlier filtering and optionally input image feature extraction)
feature_extractor, last_feature_extractor = load_feature_extractor(gen_model, last_feature_extractor, feature_extractor)
# Load generative model
model, last_gen_model = load_generative_model(gen_model, last_gen_model, experiment_name, model)

replace_to_inplace_relu(model)
ind2name = {index: wn.of2ss("%08dn" % offset).lemma_names()[0] for offset, index in utils.IMAGENET.items()}

eps = 1e-8


upsampler = realesrgan.RealESRGANer(
    scale=4,
    model_path="modelzoo/RealESRGAN_x4plus.pth",
    model=RRDBNet(num_in_ch=3, num_out_ch=3, num_feat=64, num_block=23, num_grow_ch=32, scale=4),
    tile=0,
    tile_pad=10,
    pre_pad=0,
)
for input_image_instance in tqdm(glob("/home/hans/datasets/diffuse/sorts/best/*")):

    # Prepare other variables
    name_file = "%s_%s_cls%s_inst%s" % (
        Path(input_image_instance).stem,
        gen_model,
        str(class_index) if class_index is not None else "None",
        str(input_feature_index) if input_feature_index is not None else "None",
    )

    # Load features
    if input_image_instance not in ["None", ""]:
        # print("Obtainin g instance features from input image!")
        input_feature_index = None
        input_image_tensor = preprocess_input_image(input_image_instance, int(size))
        # print("Displaying instance conditioning:")
        with torch.no_grad():
            input_features, _ = feature_extractor(input_image_tensor.cuda())
        input_features /= torch.linalg.norm(input_features, dim=-1, keepdims=True)
    elif input_feature_index is not None:
        # print("Selecting an instance from pre-extracted vectors!")
        input_features = np.load(
            "modelzoo/stored_instances/imagenet_res"
            + str(size)
            + "_rn50_"
            + feature_extractor_name
            + "_kmeans_k1000_instance_features.npy",
            allow_pickle=True,
        ).item()["instance_features"][input_feature_index : input_feature_index + 1]
    else:
        input_features = None

    # Create noise, instance and class vector
    noise_vector = truncnorm.rvs(
        -2 * truncation, 2 * truncation, size=(num_samples_total, noise_size), random_state=state
    ).astype(
        np.float32
    )  # see https://github.com/tensorflow/hub/issues/214
    noise_vector = torch.tensor(noise_vector, requires_grad=False, device="cuda")
    if input_features is not None:
        instance_vector = input_features.clone().detach().repeat(num_samples_total, 1)
    else:
        instance_vector = None
    if class_index is not None:
        # print("Conditioning on class: ", ind2name[class_index])
        input_label = torch.LongTensor([class_index] * num_samples_total)
    else:
        input_label = None
    # if input_feature_index is not None:
    #     print("Conditioning on instance with index: ", input_feature_index)

    size = int(size)
    all_outs, all_dists = [], []
    for i_bs in range(num_samples_total // batch_size + 1):
        start = i_bs * batch_size
        end = min(start + batch_size, num_samples_total)
        if start == end:
            break
        out = get_output(
            noise_vector[start:end],
            input_label[start:end] if input_label is not None else None,
            instance_vector[start:end] if instance_vector is not None else None,
        )

        if instance_vector is not None:
            # Get features from generated images + feature extractor
            out_ = preprocess_generated_image(out)
            with torch.no_grad():
                out_features, _ = feature_extractor(out_.cuda())
            out_features /= torch.linalg.norm(out_features, dim=-1, keepdims=True)
            dists = sklearn.metrics.pairwise_distances(
                out_features.cpu(), instance_vector[start:end].cpu(), metric="euclidean", n_jobs=-1
            )
            all_dists.append(np.diagonal(dists))
            all_outs.append(out.detach().cpu())
        del out
    all_outs = torch.cat(all_outs)
    all_dists = np.concatenate(all_dists)

    # Order samples by distance to conditioning feature vector and select only num_samples_ranked images
    selected_idxs = np.argsort(all_dists)[:num_samples_ranked]

    for o, out in enumerate(all_outs[selected_idxs]):
        name = "/home/hans/datasets/diffuse/sorts/beic/%s_seed%i_%i.png" % (
            name_file,
            seed if seed is not None else -1,
            o,
        )
        out = out.add(1).div(2).clamp(0, 1).mul(255).permute(1, 2, 0).cpu().numpy()
        imageio.imwrite(name, out.astype(np.uint8))
        # out, _ = upsampler.enhance(cv2.cvtColor(out, cv2.COLOR_RGB2BGR) * 255, outscale=4)
        # print(out.min().item(), out.mean().item(), out.max().item(), out.shape)
        # # print(out.min().item(), out.mean().item(), out.max().item(), out.shape)
        # # print(out.min().item(), out.mean().item(), out.max().item(), out.shape)
        # Image.fromarray(out.astype(np.uint8)).save(name)
