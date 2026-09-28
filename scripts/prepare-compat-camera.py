"""Patch pinned libdshowcapture output pin for the fixed-format compatibility prototype.

Upstream license: LGPL-2.1-or-later. Changes: Meeting Assistant, 2026-09-27.
Reject malformed/unsupported media types and avoid blocking the output allocator.
"""

import sys
from pathlib import Path

root = Path(sys.argv[1])
p = root / "source/output-filter.cpp"
s = p.read_text()


def replace(old, new):
    global s
    if s.count(old) != 1:
        raise RuntimeError("Pinned DirectShow source changed: " + old[:90])
    s = s.replace(old, new)


replace(
    "STDMETHODIMP OutputPin::QueryAccept(const AM_MEDIA_TYPE *)\n{\n"
    '\tPrintFunc(L"OutputPin::QueryAccept");\n\n\treturn S_OK;\n}',
    """bool OutputPin::IsValidMediaType(const AM_MEDIA_TYPE *pmt) const
{
    if (!pmt || pmt->majortype != MEDIATYPE_Video || pmt->formattype != FORMAT_VideoInfo ||
        !pmt->pbFormat || pmt->cbFormat < sizeof(VIDEOINFOHEADER)) return false;
    if (pmt->subtype != MEDIASUBTYPE_NV12 && pmt->subtype != MEDIASUBTYPE_I420 &&
        pmt->subtype != MEDIASUBTYPE_YUY2) return false;
    const auto *vih = reinterpret_cast<const VIDEOINFOHEADER*>(pmt->pbFormat);
    const int bits = pmt->subtype == MEDIASUBTYPE_YUY2 ? 16 : 12;
    return vih->bmiHeader.biWidth == 1280 && vih->bmiHeader.biHeight == 720 &&
           vih->bmiHeader.biBitCount == bits && vih->AvgTimePerFrame == 333333;
}
STDMETHODIMP OutputPin::QueryAccept(const AM_MEDIA_TYPE *pmt)
{
    return IsValidMediaType(pmt) ? S_OK : S_FALSE;
}""",
)
replace(
    "if (pmt == nullptr)\n\t\treturn VFW_E_INVALIDMEDIATYPE;",
    """if (!IsValidMediaType(pmt)) return VFW_E_INVALIDMEDIATYPE;
    if (filter->state != State_Stopped) return VFW_E_NOT_STOPPED;""",
)
replace(
    "\thr = pReceivePin->ReceiveConnection(this, mt);",
    """    if (!pReceivePin) return E_POINTER;
    if (pmt) {
        hr = SetFormat(const_cast<AM_MEDIA_TYPE*>(pmt));
        if (FAILED(hr)) return hr;
    }
\thr = pReceivePin->ReceiveConnection(this, mt);""",
)
replace(
    "allocator->GetBuffer(&sample, nullptr, nullptr, 0)",
    "allocator->GetBuffer(&sample, nullptr, nullptr, AM_GBF_NOWAIT)",
)
replace("void OutputPin::Stop()\n{", "void OutputPin::Stop()\n{\n    if (allocator) allocator->Decommit();")
replace(
    "} else if (riid == IID_IMemInputPin) {\n\t\tAddRef();\n\t\t*ppv = (IMemInputPin *)this;\n\t",
    "} else if (riid == IID_IMemInputPin) {\n        *ppv = nullptr;\n        return E_NOINTERFACE;\n\t",
)
p.write_text("// Modified by Meeting Assistant 2026-09-27; see prepare-compat-camera.py.\n" + s)
