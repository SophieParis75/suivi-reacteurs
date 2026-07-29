from flask import Flask, send_file
import download_doaat

app = Flask(__name__)

@app.route("/download")
def download():
    path = download_doaat.download_edf_feed()
    return send_file(path, as_attachment=True)

app.run(port=5000)
