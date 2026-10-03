"""Adapt the pinned Microsoft MIT sample; fail if upstream layout changes."""

import argparse
from pathlib import Path

OLD = "7B89B92E-FE71-42D0-8A41-E137D06EA184"
NEW = "5108191D-9AD8-44F5-B760-7A35D433A427"


def patch(root, native):
    source = root / "Samples/VirtualCamera/VirtualCameraMediaSource"
    stream = source / "SimpleMediaStream.cpp"
    text = stream.read_text(encoding="utf-8-sig")
    needle = "RETURN_IF_FAILED(m_spFrameGenerator->CreateFrame(pbuf, bufferLength, pitch, m_rgbMask));"
    if text.count(needle) != 1:
        raise ValueError("Unexpected Microsoft sample; refusing to patch")
    text = text.replace('#include "pch.h"', '#include "pch.h"\n#include "pipe_client.hpp"')
    text = text.replace("#define NUM_IMAGE_ROWS 480", "#define NUM_IMAGE_ROWS 720")
    text = text.replace("#define NUM_IMAGE_COLS 640", "#define NUM_IMAGE_COLS 1280")
    text = text.replace("const uint32_t NUM_MEDIATYPES = 2;", "const uint32_t NUM_MEDIATYPES = 1;")
    start = text.index(
        "        RETURN_IF_FAILED(MFCreateMediaType(&spMediaType));", text.index("mediaTypeList[0]")
    )
    end = text.index("        RETURN_IF_FAILED(MFCreateAttributes(&m_spAttributes", start)
    text = text[:start] + text[end:]
    text = text.replace(
        needle, "HRESULT frameResult = m_programReader.copy_frame(pbuf, bufferLength, pitch);"
    )
    text = text.replace(
        "RETURN_IF_FAILED(buffer2D->Unlock2D());",
        "RETURN_IF_FAILED(buffer2D->Unlock2D());\n        RETURN_IF_FAILED(frameResult);",
    )
    text = text.replace(
        "spMediaType->SetGUID(MF_MT_SUBTYPE, MFVideoFormat_NV12);",
        "spMediaType->SetGUID(MF_MT_SUBTYPE, MFVideoFormat_NV12);\n"
        "        spMediaType->SetUINT32(MF_MT_YUV_MATRIX, MFVideoTransferMatrix_BT709);\n"
        "        spMediaType->SetUINT32(MF_MT_VIDEO_NOMINAL_RANGE, MFNominalRange_16_235);",
    )
    text = text.replace(
        "        m_bIsShutdown = true;", "        m_bIsShutdown = true;\n        m_programReader.reset();"
    )
    stream.write_text(text, encoding="utf-8")
    header = source / "SimpleMediaStream.h"
    header_text = header.read_text(encoding="utf-8-sig")
    anchor = "        winrt::slim_mutex  m_Lock;"
    if header_text.count(anchor) != 1:
        raise ValueError("Unexpected stream header; refusing to patch")
    header_text = header_text.replace(
        '#include "SimpleMediaSource.h"', '#include "SimpleMediaSource.h"\n#include "pipe_client.hpp"'
    )
    header_text = header_text.replace(anchor, anchor + "\n        ma::ProgramReader m_programReader;")
    header.write_text(header_text, encoding="utf-8")
    for name in ("protocol.hpp", "pipe_client.hpp"):
        (source / name).write_bytes((native / name).read_bytes())
    for file in source.glob("*.h"):
        text = file.read_text(encoding="utf-8-sig")
        text = text.replace(OLD, NEW).replace(OLD.lower(), NEW.lower())
        text = text.replace(
            "0x7b89b92e, 0xfe71, 0x42d0, 0x8a, 0x41, 0xe1, 0x37, 0xd0, 0x6e, 0xa1, 0x84",
            "0x5108191d, 0x9ad8, 0x44f5, 0xb7, 0x60, 0x7a, 0x35, 0xd4, 0x33, 0xa4, 0x27",
        )
        file.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("native", type=Path)
    args = parser.parse_args()
    patch(args.source, args.native)
