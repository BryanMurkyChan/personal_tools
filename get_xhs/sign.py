"""小红书签名算法。

参考 MediaCrawler 的 help.py 和 xhs_sign.py 实现：
- 自定义CRC32变体（mrc32）
- 自定义Base64编码（shuffled alphabet）
- UTF-8 percent-encoding
- x-s-common 和 x-b3-traceid 组装
"""

import ctypes
import json
import platform
import random
import urllib.parse

# ---- 常量 ----

# 小红书自定义Base64字母表（shuffled order）
CUSTOM_B64_ALPHABET = "ZmserbBoHQtNP+wOcza/LpngG8yJq42KWYj0DSfdikx3VT16IlUAFM97hECvuRX5"
_B64_LOOKUP = list(CUSTOM_B64_ALPHABET)

# B3 trace ID 字符集
_B3_TRACEID_ALPHABET = "abcdef0123456789"

# CRC32 查找表（小红书自定义多项式）
CRC32_TABLE = [
    0, 1996959894, 3993919788, 2567524794, 124634137, 1886057615, 3915621685,
    2657392035, 249268274, 2044508324, 3772115230, 2547177864, 162941995,
    2125561021, 3887607047, 2428444049, 498536548, 1789927666, 4089016648,
    2227061214, 450548861, 1843258603, 4107580753, 2211677639, 325883990,
    1684777152, 4251122042, 2321926636, 335633487, 1661365465, 4195302755,
    2366115317, 997073096, 1281953886, 3579855332, 2724688242, 1006888145,
    1258607687, 3524101629, 2768942443, 901097722, 1119000684, 3686517206,
    2898065728, 853044451, 1172266101, 3705015759, 2882616665, 651767980,
    1373503546, 3369554304, 3218104598, 565507253, 1454621731, 3485111705,
    3099436303, 671266974, 1594198024, 3322730930, 2970347812, 795835527,
    1483230225, 3244367275, 3060149565, 1994146192, 31158534, 2563907772,
    4023717930, 1907459465, 112637215, 2680153253, 3904427059, 2013776290,
    251722036, 2517215374, 3775830040, 2137656763, 141376813, 2439277719,
    3865271297, 1802195444, 476864866, 2238001368, 4066508878, 1812370925,
    453092731, 2181625025, 4111451223, 1706088902, 314042704, 2344532202,
    4240017532, 1658658271, 366619977, 2362670323, 4224994405, 1303535960,
    984961486, 2747007092, 3569037538, 1256170817, 1037604311, 2765210733,
    3554079995, 1131014506, 879679996, 2909243462, 3663771856, 1141124467,
    855842277, 2852801631, 3708648649, 1342533948, 654459306, 3188396048,
    3373015174, 1466479909, 544179635, 3110523913, 3462522015, 1591671054,
    702138776, 2966460450, 3352799412, 1504918807, 783551873, 3082640443,
    3233442989, 3988292384, 2596254646, 62317068, 1957810842, 3939845945,
    2647816111, 81470997, 1943803523, 3814918930, 2489596804, 225274430,
    2053790376, 3826175755, 2466906013, 167816743, 2097651377, 4027552580,
    2265490386, 503444072, 1762050814, 4150417245, 2154129355, 426522225,
    1852507879, 4275313526, 2312317920, 282753626, 1742555852, 4189708143,
    2394877945, 397917763, 1622183637, 3604390888, 2714866558, 953729732,
    1340076626, 3518719985, 2797360999, 1068828381, 1219638859, 3624741850,
    2936675148, 906185462, 1090812512, 3747672003, 2825379669, 829329135,
    1181335161, 3412177804, 3160834842, 628085408, 1382605366, 3423369109,
    3138078467, 570562233, 1426400815, 3317316542, 2998733608, 733239954,
    1555261956, 3268935591, 3050360625, 752459403, 1541320221, 2607071920,
    3965973030, 1969922972, 40735498, 2617837225, 3943577151, 1913087877,
    83908371, 2512341634, 3803740692, 2075208622, 213261112, 2463272603,
    3855990285, 2094854071, 198958881, 2262029012, 4057260610, 1759359992,
    534414190, 2176718541, 4139329115, 1873836001, 414664567, 2282248934,
    4279200368, 1711684554, 285281116, 2405801727, 4167216745, 1634467795,
    376229701, 2685067896, 3608007406, 1308918612, 956543938, 2808555105,
    3495958263, 1231636301, 1047427035, 2932959818, 3654703836, 1088359270,
    936918000, 2847714899, 3736837829, 1202900863, 817233897, 3183342108,
    3401237130, 1404277552, 615818150, 3134207493, 3453421203, 1423857449,
    601450431, 3009837614, 3294710456, 1567103746, 711928724, 3020668471,
    3272380065, 1510334235, 755167117,
]


# ---- 内部函数 ----

def _right_shift_unsigned(num: int, bit: int = 0) -> int:
    """模拟JavaScript的无符号右移（>>>）。"""
    val = ctypes.c_uint32(num).value >> bit
    MAX32INT = 4294967295
    return (val + (MAX32INT + 1)) % (2 * (MAX32INT + 1)) - MAX32INT - 1


def mrc32(data: str) -> int:
    """小红书自定义CRC32变体，用于签名的x9字段。"""
    o = -1
    limit = min(57, len(data))
    for n in range(limit):
        o = CRC32_TABLE[(o & 255) ^ ord(data[n])] ^ _right_shift_unsigned(o, 8)
    return o ^ -1 ^ 3988292384


def _percent_encode(text: str) -> list[int]:
    """模拟JS encodeURIComponent，返回UTF-8字节列表。"""
    encoded = urllib.parse.quote(text, safe="~()*!.'")
    result = []
    i = 0
    while i < len(encoded):
        ch = encoded[i]
        if ch == "%":
            result.append(int(encoded[i + 1:i + 3], 16))
            i += 3
        else:
            result.append(ord(ch))
            i += 1
    return result


def _triplet_to_base64(e: int) -> str:
    """将24-bit整数编码为4个自定义Base64字符。"""
    return (
        _B64_LOOKUP[(e >> 18) & 63]
        + _B64_LOOKUP[(e >> 12) & 63]
        + _B64_LOOKUP[(e >> 6) & 63]
        + _B64_LOOKUP[e & 63]
    )


def _encode_chunk(data: list[int], start: int, end: int) -> str:
    """编码数据块为自定义Base64字符串。"""
    result = []
    for i in range(start, end, 3):
        c = ((data[i] << 16) & 0xFF0000) + ((data[i + 1] << 8) & 0xFF00) + (data[i + 2] & 0xFF)
        result.append(_triplet_to_base64(c))
    return "".join(result)


def _custom_base64_encode(data: list[int]) -> str:
    """自定义Base64编码（小红书shuffled alphabet）。"""
    length = len(data)
    remainder = length % 3
    chunks = []

    main_length = length - remainder
    for i in range(0, main_length, 16383):
        chunks.append(_encode_chunk(data, i, min(i + 16383, main_length)))

    if remainder == 1:
        a = data[length - 1]
        chunks.append(_B64_LOOKUP[a >> 2] + _B64_LOOKUP[(a << 4) & 63] + "==")
    elif remainder == 2:
        a = (data[length - 2] << 8) + data[length - 1]
        chunks.append(
            _B64_LOOKUP[a >> 10]
            + _B64_LOOKUP[(a >> 4) & 63]
            + _B64_LOOKUP[(a << 2) & 63]
            + "="
        )

    return "".join(chunks)


def _get_os_string() -> str:
    """获取操作系统标识字符串。"""
    system = platform.system()
    if system == "Windows":
        return "Windows"
    elif system == "Darwin":
        return "Mac OS"
    else:
        return "Linux"


# ---- public API ----

def generate_x_b3_traceid() -> str:
    """生成 x-b3-traceid（16位随机hex，受限字母表）。"""
    return "".join(random.choice(_B3_TRACEID_ALPHABET) for _ in range(16))


def sign(a1: str = "", b1: str = "", x_s: str = "", x_t: str = "") -> dict:
    """组装签名字典。

    Args:
        a1: Cookie中的a1值
        b1: localStorage中的b1值
        x_s: 浏览器 window._webmsxyw() 返回的 X-s
        x_t: 浏览器 window._webmsxyw() 返回的 X-t

    Returns:
        {"x-s": ..., "x-t": ..., "x-s-common": ..., "x-b3-traceid": ...}
    """
    x_t_str = str(x_t)
    common = {
        "s0": 3,
        "s1": "",
        "x0": "1",
        "x1": "4.2.2",
        "x2": _get_os_string(),
        "x3": "xhs-pc-web",
        "x4": "4.74.0",
        "x5": a1,
        "x6": x_t_str,
        "x7": x_s,
        "x8": b1,
        "x9": mrc32(x_t_str + x_s + b1),
        "x10": 154,
        "x11": "normal",
    }
    json_str = json.dumps(common, separators=(",", ":"), ensure_ascii=False)
    encoded_bytes = _percent_encode(json_str)
    x_s_common = _custom_base64_encode(encoded_bytes)
    x_b3_traceid = generate_x_b3_traceid()

    return {
        "x-s": x_s,
        "x-t": x_t_str,
        "x-s-common": x_s_common,
        "x-b3-traceid": x_b3_traceid,
    }
