@app.route("/slice", methods=["POST"])
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
