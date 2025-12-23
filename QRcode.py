import qrcode
from qrcode.image.pil import PilImage

# Text with love emojis 💖😍✨
text = "You look Beautiful 💖😍✨"

# Create a QRCode object for styling
qr = qrcode.QRCode(
    version=1,  # QR code size (1-40)
    error_correction=qrcode.constants.ERROR_CORRECT_H,
    box_size=10,  # size of each box
    border=4,     # thickness of the border
)

# Add data
qr.add_data(text)
qr.make(fit=True)

# Make a colored QR code with heart theme
img = qr.make_image(
    fill_color="red",     # QR code color
    back_color="pink",    # background color
    image_factory=PilImage
)

# Save the QR code
img.save(r"C:\Users\SuleimanAbdulsalam\Downloads\Python scripts\myqrcode.png")

print("❤️✨ Fancy heart-themed QR code saved at myqrcode.png ✨❤️")
