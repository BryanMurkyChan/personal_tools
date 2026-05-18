---
name: look
description: Describe the latest image/screenshot using Zhipu GLM-4.6V vision model. Use when the user pastes an image and it shows [Unsupported Image], or when the user asks to "look at this", "describe this image", "看看这张图", or "看图".
allowed-tools: [Bash, Read, Write]
---

# Look - Image Description via Vision Model

When the user sends an image in chat and it appears as `[Unsupported Image]`, or asks me to look at an image, use the Zhipu GLM-4.6V-FlashX vision model to describe it.

## Modes

| Mode | Behavior |
|------|----------|
| (none) `default` | Auto-classify image type (UI/Code/Document/Photo/Error), apply type-appropriate description |
| `ui` | UI-focused description with spatial analysis (area ratios, whitespace distribution, information density) |
| `text` | Text-only extraction, plain list |
| `full` | Legacy 10-section exhaustive catalog |

Any other string is treated as a raw custom prompt (backward compatible).

## How It Works

The describe_image.py script sends the image to Zhipu's multimodal API and returns a description.

## Steps

1. If the user pasted an image and it shows `[Unsupported Image]`, find the latest screenshot:
   - Check `C:/Users/bryan/AppData/Local/Temp/` for recent PNG files
   - Check `/tmp/` for recent PNG files
   - The latest `ScreenShot_*.png` is usually the one the user just sent
   - If no screenshot found, use `find` to locate the most recently modified image

2. Run the vision script:
   ```
   /c/Users/bryan/anaconda3/envs/miao_v2/python.exe C:/Users/bryan/.claude/mcp-servers/describe_image.py "<image_path>" [mode]
   ```

3. Display the description to the user.

4. If the user provides a specific image path, use that directly instead of searching.

## Script Location

`C:/Users/bryan/.claude/mcp-servers/describe_image.py`

## Note

- The script requires `ZHIPU_API_KEY` environment variable (already configured)
- Uses `openai` and `Pillow` libraries (available in miao_v2 conda env)
