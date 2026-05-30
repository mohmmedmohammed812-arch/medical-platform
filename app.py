import os
import io
import json
import zipfile
import base64
import uuid

import numpy as np
from flask import Flask, request, jsonify, render_template, send_from_directory
from PIL import Image
import pydicom

app = Flask(name)

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


def normalize(arr):
    arr = arr.astype(np.float32)
    mn, mx = arr.min(), arr.max()
    if mx == mn:
        return np.zeros_like(arr, dtype=np.uint8)
    return ((arr - mn) / (mx - mn) * 255).astype(np.uint8)


def to_png(arr2d):
    img = Image.fromarray(arr2d, mode="L")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def try_dicom(path):
    try:
        ds = pydicom.dcmread(str(path), force=True)
        _ = ds.pixel_array
        return ds
    except Exception:
        return None


def find_dicoms(folder):
    results = []
    for root, _, files in os.walk(folder):
        for f in files:
            fp = os.path.join(root, f)
            ds = try_dicom(fp)
            if ds is not None:
                results.append((fp, ds))
    return results


def sort_slices(dicom_list):
    def key(item):
        _, ds = item
        try:
            return float(ds.InstanceNumber)
        except Exception:
            pass
        try:
            return float(ds.ImagePositionPatient[2])
        except Exception:
            pass
        return str(item[0])
    return sorted(dicom_list, key=key)


def build_volume(sorted_dicoms):
    slices = []
    for _, ds in sorted_dicoms:
        arr = ds.pixel_array.astype(np.float32)
        slope = float(getattr(ds, "RescaleSlope", 1))
        inter = float(getattr(ds, "RescaleIntercept", 0))
        slices.append(arr * slope + inter)
    return np.stack(slices, axis=0)


def get_mpr(volume, z, y, x):
    Z, Y, X = volume.shape
    z = max(0, min(Z - 1, z))
    y = max(0, min(Y - 1, y))
    x = max(0, min(X - 1, x))
    axial = normalize(volume[z, :, :])
    coronal = normalize(np.flipud(volume[:, y, :]))
    sagittal = normalize(np.flipud(volume[:, :, x]))
    return axial, coronal, sagittal


store = {}


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/upload", methods=["POST"])
def upload():
    if "file" not in request.files:
        return jsonify({"error": "No file"}), 400
    f = request.files["file"]
    save_path = os.path.join(UPLOAD_FOLDER, f.filename)
    f.save(save_path)

    ext = os.path.splitext(f.filename)[1].lower()
    dicoms = []

    if ext == ".zip":
        dest = os.path.join(UPLOAD_FOLDER, f.filename + "_extracted")
        os.makedirs(dest, exist_ok=True)
        with zipfile.ZipFile(save_path, "r") as z:
            z.extractall(dest)
        dicoms = find_dicoms(dest)
    else:
        ds = try_dicom(save_path)
        if ds:
            dicoms = [(save_path, ds)]
        else:
            dicoms = find_dicoms(UPLOAD_FOLDER)

    if not dicoms:
        return jsonify({"error": "No DICOM found"}), 422

    sorted_dicoms = sort_slices(dicoms)
    volume = build_volume(sorted_dicoms)
    Z, Y, X = volume.shape

    _, first = sorted_dicoms[0]
    meta = {
        "patient": str(getattr(first, "PatientName", "Unknown")),
        "modality": str(getattr(first, "Modality", "Unknown")),
        "study_date": str(getattr(first, "StudyDate", "Unknown")),
        "slices": Z,
        "rows": Y,
        "cols": X,
        "files_found": len(dicoms),
    }

    sid = str(uuid.uuid4())
    store[sid] = {"volume": volume, "meta": meta}

    ax, co, sa = get_mpr(volume, Z // 2, Y // 2, X // 2)
    return jsonify({
        "session_id": sid,
        "meta": meta,
        "z": Z // 2, "y": Y // 2, "x": X // 2,
        "axial": to_png(ax),
        "coronal": to_png(co),
        "sagittal": to_png(sa),
    })
[5/30/2026 9:24 PM] Muhammed Imran: @app.route("/slice", methods=["POST"])
def slice_view():
    body = request.get_json(silent=True) or {}
    sid = body.get("session_id")
    sess = store.get(sid)
    if not sess:
        return jsonify({"error": "Session not found"}), 404
    volume = sess["volume"]
    Z, Y, X = volume.shape
    z = int(body.get("z", Z // 2))
    y = int(body.get("y", Y // 2))
    x = int(body.get("x", X // 2))
    ax, co, sa = get_mpr(volume, z, y, x)
    return jsonify({
        "axial": to_png(ax),
        "coronal": to_png(co),
        "sagittal": to_png(sa),
        "z": z, "y": y, "x": x,
    })


@app.route("/volume_data", methods=["POST"])
def volume_data():
    body = request.get_json(silent=True) or {}
    sid = body.get("session_id")
    step = max(1, int(body.get("step", 2)))
    sess = store.get(sid)
    if not sess:
        return jsonify({"error": "Session not found"}), 404
    volume = sess["volume"]
    Z, Y, X = volume.shape
    slices_b64 = []
    for z in range(0, Z, step):
        slices_b64.append(to_png(normalize(volume[z])))
    return jsonify({
        "slices": slices_b64,
        "Z": Z, "Y": Y, "X": X,
    })


@app.route("/uploads/<path:filename>")
def serve_upload(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)


if name == "main":
    app.run(debug=True)
