import fitz
import os
import csv
from PIL import Image, ImageDraw

os.makedirs("pdf_slices", exist_ok=True)
pdf_folder = "pdf_files"
csv_output = "pdf_issues_report.csv"

def find_handwriting_clusters(image_path, threshold=80, cluster_size=3):
    img = Image.open(image_path).convert("L")
    width, height = img.size
    pixels = img.load()
    visited = [[False for _ in range(height)] for _ in range(width)]
    handwriting_clusters = []

    def dfs(x, y):
        stack = [(x, y)]
        size = 0
        coords = []
        while stack:
            cx, cy = stack.pop()
            if 0 <= cx < width and 0 <= cy < height and not visited[cx][cy] and pixels[cx, cy] < threshold:
                visited[cx][cy] = True
                size += 1
                coords.append((cx, cy))
                for dx in [-1, 0, 1]:
                    for dy in [-1, 0, 1]:
                        if dx != 0 or dy != 0:
                            stack.append((cx + dx, cy + dy))
        return size, coords

    for x in range(width):
        for y in range(height):
            if not visited[x][y] and pixels[x, y] < threshold:
                size, coords = dfs(x, y)
                if size >= cluster_size:
                    xs = [c[0] for c in coords]
                    ys = [c[1] for c in coords]
                    cluster_width = max(xs) - min(xs)
                    cluster_height = max(ys) - min(ys)
                    print(f"Cluster found: width={cluster_width}, height={cluster_height}, size={size}")
                    # Relaxed filter: width > 30 and height > 3
                    if cluster_width > 30 and cluster_height > 3:
                        handwriting_clusters.append(coords)

    return handwriting_clusters

def save_cluster_heatmap(image_path, clusters):
    img = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(img)
    for cluster in clusters:
        for (x, y) in cluster:
            draw.point((x, y), fill=(255, 0, 0))
    heatmap_path = image_path.replace(".png", "_heatmap.png")
    img.save(heatmap_path)
    print(f"Saved heatmap: {heatmap_path}")

with open(csv_output, mode='w', newline='', encoding='utf-8') as csvfile:
    fieldnames = ['File Name', 'Residency Verification Found', 'Has # in Address', 'Signature Missing', 'ValidClusters']
    writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
    writer.writeheader()

    if not os.path.exists(pdf_folder):
        print(f"Folder '{pdf_folder}' does not exist.")
    else:
        for filename in os.listdir(pdf_folder):
            if not filename.lower().endswith(".pdf"):
                continue

            file_path = os.path.join(pdf_folder, filename)
            doc = fitz.open(file_path)
            page = doc[0]

            print(f"\nScanning file: {filename}")
            residency_found = bool(page.search_for("Residency Verification Form"))

            # Address detection
            step_two_rects = page.search_for("Step Two")
            has_hash_in_address = False
            address_image_path = f"pdf_slices/{filename}_address_area.png"
            if step_two_rects:
                step_two_rect = step_two_rects[0]
                address_rect = fitz.Rect(step_two_rect.x0, step_two_rect.y1, step_two_rect.x1 + 300, step_two_rect.y1 + 100)
            else:
                address_rect = fitz.Rect(50, 150, page.rect.width - 50, 300)
            pix = page.get_pixmap(clip=address_rect)
            pix.save(address_image_path)
            address_text = page.get_textbox(address_rect)
            has_hash_in_address = '#' in address_text

            # Signature detection
            signature_rects = page.search_for("Signature:")
            sig_image_path = f"pdf_slices/{filename}_signature_area.png"
            valid_clusters = 0
            signature_missing = True
            if signature_rects:
                sig_rect = signature_rects[0]
                full_signature_area = fitz.Rect(sig_rect.x0, sig_rect.y0, sig_rect.x1 + 200, sig_rect.y1 + 50)
            else:
                full_signature_area = fitz.Rect(50, page.rect.height - 150, page.rect.width - 50, page.rect.height - 50)

            # Middle 50% crop
            middle_crop = fitz.Rect(
                full_signature_area.x0,
                full_signature_area.y0 + 0.25 * (full_signature_area.y1 - full_signature_area.y0),
                full_signature_area.x1,
                full_signature_area.y0 + 0.75 * (full_signature_area.y1 - full_signature_area.y0)
            )

            pix = page.get_pixmap(clip=middle_crop)
            pix.save(sig_image_path)

            clusters = find_handwriting_clusters(sig_image_path)
            valid_clusters = len(clusters)
            save_cluster_heatmap(sig_image_path, clusters)

            signature_missing = valid_clusters == 0

            writer.writerow({
                'File Name': filename,
                'Residency Verification Found': residency_found,
                'Has # in Address': has_hash_in_address,
                'Signature Missing': signature_missing,
                'ValidClusters': valid_clusters
            })

print(f"\n✅ Analysis complete. Results saved to '{csv_output}' and slices saved in 'pdf_slices'.")