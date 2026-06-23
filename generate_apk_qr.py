"""
APK ダウンロード用QRコード生成スクリプト
GitHub Releases ページの URL を QR コード化して PNG 保存 + 表示する
"""
import sys
import os

def generate_qr(url: str, output_path: str = "apk_qr.png"):
    try:
        import qrcode
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        print("インストール中... pip install qrcode[pil] pillow")
        os.system(f'"{sys.executable}" -m pip install "qrcode[pil]" pillow -q')
        import qrcode
        from PIL import Image, ImageDraw, ImageFont

    # QRコード生成
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=12,
        border=3,
    )
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#0a2a4a", back_color="white")

    # キャプション追加
    W, H = img.size
    caption_h = 60
    new_img = Image.new("RGB", (W, H + caption_h), "white")
    new_img.paste(img, (0, 0))

    draw = ImageDraw.Draw(new_img)
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/meiryo.ttc", 18)
        small = ImageFont.truetype("C:/Windows/Fonts/meiryo.ttc", 12)
    except Exception:
        font = ImageFont.load_default()
        small = font

    draw.text((W // 2, H + 14), "6艇スタート分析", fill="#0a2a4a",
              font=font, anchor="mm")
    draw.text((W // 2, H + 40), "APKをダウンロード", fill="#555555",
              font=small, anchor="mm")

    new_img.save(output_path)
    print(f"✓ QRコードを保存しました: {output_path}")

    # 自動で開く
    import subprocess
    subprocess.Popen(["explorer", output_path])

    return output_path


if __name__ == "__main__":
    # GitHub Releases URL を設定してください
    # 例: https://github.com/ユーザー名/リポジトリ名/releases/latest
    if len(sys.argv) > 1:
        url = sys.argv[1]
    else:
        url = input("APKダウンロードURL (GitHub Releases URL) を入力してください:\n> ").strip()
        if not url:
            print("URLが入力されていません。")
            sys.exit(1)

    out = os.path.join(os.path.dirname(__file__), "apk_qr.png")
    generate_qr(url, out)
    print(f"\nこのQRコードをスマホで読み取るとAPKをダウンロードできます。")
