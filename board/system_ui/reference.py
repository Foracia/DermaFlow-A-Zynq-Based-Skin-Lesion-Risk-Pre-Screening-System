"""Integer reference for the AXIS core; no third-party dependencies required."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    enable: int = 1
    x0: int = 320
    y0: int = 180
    width: int = 640
    height: int = 360
    mean_min: int = 40
    mean_max: int = 210
    dark_level: int = 16
    bright_level: int = 239
    dark_max_bp: int = 200
    bright_max_bp: int = 200
    sharp_min: int = 20
    stable_n: int = 3


def statistics(pixels, frame_width, frame_height, cfg):
    """Pixels are integer B:G:R packed words, R occupies bits 7:0."""
    gray = [[((77 * (p & 255) + 150 * ((p >> 8) & 255)
               + 29 * ((p >> 16) & 255) + 128) >> 8)
             for p in row] for row in pixels]
    roi = [gray[y][x]
           for y in range(frame_height) for x in range(frame_width)
           if cfg.x0 <= x < cfg.x0 + cfg.width and cfg.y0 <= y < cfg.y0 + cfg.height]
    gradients = []
    for y in range(max(2, cfg.y0 + 2), min(frame_height, cfg.y0 + cfg.height)):
        for x in range(max(2, cfg.x0 + 2), min(frame_width, cfg.x0 + cfg.width)):
            top = gray[y-2][x-2:x+1]
            mid = gray[y-1][x-2:x+1]
            bot = gray[y][x-2:x+1]
            gx = top[2] + 2*mid[2] + bot[2] - top[0] - 2*mid[0] - bot[0]
            gy = bot[0] + 2*bot[1] + bot[2] - top[0] - 2*top[1] - top[2]
            gradients.append(abs(gx) + abs(gy))
    return dict(pixel_count=len(roi), luma_sum=sum(roi),
                dark_count=sum(v < cfg.dark_level for v in roi),
                bright_count=sum(v > cfg.bright_level for v in roi),
                gradient_count=len(gradients), gradient_sum=sum(gradients))


def evaluate(stats, cfg, frame_width, frame_height, malformed=False):
    valid = bool(cfg.enable and cfg.width >= 3 and cfg.height >= 3
                 and cfg.x0 + cfg.width <= frame_width and cfg.y0 + cfg.height <= frame_height
                 and cfg.mean_min <= cfg.mean_max and cfg.dark_level < cfg.bright_level
                 and 0 <= cfg.dark_max_bp <= 10000 and 0 <= cfg.bright_max_bp <= 10000
                 and stats['pixel_count'] == cfg.width * cfg.height
                 and stats['gradient_count'] == (cfg.width-2) * (cfg.height-2) and not malformed)
    n, total = stats['pixel_count'], stats['luma_sum']
    exposure = valid and cfg.mean_min*n <= total <= cfg.mean_max*n
    exposure = exposure and stats['dark_count']*10000 <= cfg.dark_max_bp*n
    exposure = exposure and stats['bright_count']*10000 <= cfg.bright_max_bp*n
    sharp = valid and stats['gradient_count'] > 0 and stats['gradient_sum'] >= cfg.sharp_min*stats['gradient_count']
    return valid, bool(exposure), bool(sharp), bool(exposure and sharp)


def display_statistics(stats):
    n, g = stats['pixel_count'], stats['gradient_count']
    return dict(mean_luma=stats['luma_sum']/n if n else None,
                dark_ratio=stats['dark_count']/n if n else None,
                bright_ratio=stats['bright_count']/n if n else None,
                sharpness_score=stats['gradient_sum']/g if g else None)
