# Maua Diffusion

Make visual art with diffusion models!

The `processors/` folder contains a number of wrappers around state-of-the-art diffusion models like Stable Diffusion, OpenAI's Guided Diffusion, the secondary model method a.k.a. Disco Diffusion, and more!

## Image Synthesis

`image.py` allows you to generate images using any of the implemented diffusion models.
It also contains functionality for progressively increasing the size of the image as well as scaling to arbitrary sizes through automatic tiling.
See `python -m maua.diffusion.image --help` for information on all of the parameters.

Generating a 1024px image with GLID3-XL.

```bash
python -m maua.diffusion.image \
    --init path/to/an/interesting/starting/image.jpg \
    --text "A beautiful, well-thought-out prompt with extra vitamins" \
    --diffusion glid3xl \
    --cfg-scale 10 \
    --sizes 256,256 1024,1024 \
    --skips 0.5 0.8 \
    --stitch \
    --tile-size 256
```

## Video Stylization

`video.py` supports styling videos, keeping coherence over time by using optical flow (similar to [Disco Diffusion Warp by @sxela](https://github.com/Sxela/DiscoDiffusion-Warp)).
This script also supports all of the diffusion models.
See `python -m maua.diffusion.video --help` for information on all of the parameters.

Stylizing a video with a text and image using Disco-like secondary model diffusion.

```bash
python -m maua.diffusion.video \
    --init path/to/a/video/with/cool/movement.mp4 \
    --text "An epic prompt made by a zombie unicorn" \
    --style path/to/an/image/with/a/cool/style.png \
    --diffusion guided \
    --guidance-speed fast \
    --clip-scale 2500 \
    --style-scale 750 \
    --color-match-scale 1500 \
    --blend 20 \
    --consistency-trust 0.5 \
    --size 512,512 \
    --first-skip 0.2 \
    --skip 0.7
```

Stylizing a video with Stable Diffusion.

```bash
python -m maua.diffusion.video \
    --init path/to/a/video/with/cool/movement.mp4 \
    --text "Some poem written by me" \
    --diffusion stable \
    --blend 50 \
    --consistency-trust 0.125 \
    --size 512,512 \
    --first-skip 0.2 \
    --skip 0.8 \
    --flow-exaggeration 5 \
    --sharpness 2 \
    --hist-persist
```

More advanced tutorials will be added soon.
