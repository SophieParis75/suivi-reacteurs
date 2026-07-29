import requests

def download_edf_feed(output_path="edf_doaat.xml"):
    url = "https://www.edf.fr/en/toutes-les-indisponibilites-doaat/feed"
    r = requests.get(url, timeout=10)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(r.text)

    return output_path
