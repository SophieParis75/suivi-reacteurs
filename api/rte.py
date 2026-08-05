except urllib.error.HTTPError as e:
            # Conformément au guide RTE : 404 = "No data found"
            if e.code == 404:
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps({"generation_unavailabilities": []}).encode())
            else:
                try:
                    error_body = e.read().decode('utf-8')
                except Exception:
                    error_body = str(e)

                self.send_response(e.code)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps({
                    "error": f"RTE API HTTP {e.code}",
                    "details": error_body
                }).encode())
