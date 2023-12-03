import torch


torch.set_float32_matmul_precision("high")

import argparse  # noqa: E402
import sys  # noqa: E402

from diffusers import DiffusionPipeline, AutoencoderKL  # noqa: E402


sys.path.append(".")
from utils import create_parser, benchmark_fn, bytes_to_giga_bytes, generate_csv_dict, write_to_csv  # noqa: E402


CKPT_ID = "stabilityai/stable-diffusion-xl-base-1.0"
PROMPT = "ghibli style, a fantasy landscape with castles"


def apply_dynamic_quant_fn(m):
    from torchao.quantization import apply_dynamic_quant

    if isinstance(m, (torch.nn.Conv2d, torch.nn.Linear)):
        if m.weight.size(1) <= 1280 and m.weight.size(0) <= 1280:
            return m
        if m.weight.size(1) == 640 and m.weight.size(0) == 5120:
            return m
        if m.weight.size(1) == 2048 and m.weight.size(0) == 2560:
            return m
        if m.weight.size(1) == 2048 and m.weight.size(0) == 1280:
            return m 
        else:
            apply_dynamic_quant(m)
            return m


def load_pipeline(args):
    dtype = torch.float32 if args.no_fp16 else torch.float16
    pipe = DiffusionPipeline.from_pretrained(CKPT_ID, torch_dtype=dtype, use_safetensors=True)
    
    if not args.upcast_vae:
        pipe.vae = AutoencoderKL.from_pretrained("madebyollin/sdxl-vae-fp16-fix", torch_dtype=dtype)
    
    if args.enable_fused_projections:
        pipe.enable_fused_qkv_projections()

    if args.upcast_vae:
        pipe.upcast_vae()

    if args.no_sdpa:
        pipe.unet.set_default_attn_processor()
        pipe.vae.set_default_attn_processor()
    
    pipe = pipe.to("cuda")

    if args.compile_unet:
        pipe.unet.to(memory_format=torch.channels_last)
        print("Compile UNet")

        if args.compile_mode == "max-autotune" and args.change_comp_config:
            torch._inductor.config.conv_1x1_as_mm = True
            torch._inductor.config.coordinate_descent_tuning = True

        if args.do_quant:
            pipe.unet.apply(apply_dynamic_quant_fn)
            torch._inductor.config.force_fuse_int_mm_with_mul = True

        if args.compile_mode == "max-autotune":
            pipe.unet = torch.compile(pipe.unet, mode=args.compile_mode)
        else:
            pipe.unet = torch.compile(pipe.unet, mode=args.compile_mode, fullgraph=True)

    if args.compile_vae:
        pipe.vae.to(memory_format=torch.channels_last)
        print("Compile VAE")

        if args.compile_mode == "max-autotune" and args.change_comp_config:
            torch._inductor.config.conv_1x1_as_mm = True
            torch._inductor.config.coordinate_descent_tuning = True

        if args.do_quant:
            pipe.vae.apply(apply_dynamic_quant_fn)
            torch._inductor.config.force_fuse_int_mm_with_mul = True

        if args.compile_mode == "max-autotune":
            pipe.vae.decode = torch.compile(pipe.vae.decode, mode=args.compile_mode)
        else:
            pipe.vae.decode = torch.compile(pipe.vae.decode, mode=args.compile_mode, fullgraph=True)

    pipe.set_progress_bar_config(disable=True)
    return pipe


def run_inference(pipe, args):
    _ = pipe(
        prompt=PROMPT,
        num_inference_steps=args.num_inference_steps,
        num_images_per_prompt=args.batch_size,
    )


def main(args) -> dict:
    pipeline = load_pipeline(args)
    
    # Warmup.
    run_inference(pipeline, args)
    run_inference(pipeline, args)
    run_inference(pipeline, args)

    time = benchmark_fn(run_inference, pipeline, args)  # in seconds.
    memory = bytes_to_giga_bytes(torch.cuda.max_memory_allocated())  # in GBs.

    data_dict = generate_csv_dict(
        pipeline_cls=str(pipeline.__class__.__name__),
        ckpt=CKPT_ID,
        args=args,
        time=time,
        memory=memory,
    )
    return data_dict


if __name__ == "__main__":
    parser = create_parser()
    args = parser.parse_args()

    if not args.compile_unet:
        args.compile_mode = "NA"

    data_dict = main(args)

    name = (
        CKPT_ID.replace("/", "_")
        + f"fp16@{args.no_fp16}-sdpa@{args.no_sdpa}-bs@{args.batch_size}-fuse@{args.enable_fused_projections}-upcast_vae@{args.upcast_vae}-steps@{args.num_inference_steps}-unet@{args.compile_unet}-vae@{args.compile_vae}-mode@{args.compile_mode}-change_comp_config@{args.change_comp_config}-do_quant@{args.do_quant}.csv"
    )
    write_to_csv(name, data_dict)
