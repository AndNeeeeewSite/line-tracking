import cv2
cam_num = 1 

def nothing(x):
    pass

video = cv2.VideoCapture(cam_num)
if not video.isOpened():
    print(f"Не вдалося відкрити джерело відео [{cam_num}]")
    exit()

window_name = "тет маски"
cv2.namedWindow(window_name)

cv2.createTrackbar("Threshold", window_name, 150, 255, nothing)
cv2.createTrackbar("Blur (Odd)", window_name, 5, 21, nothing)

print("--- тест маски ---")
print("'q' для виходу")

while True:
    ok, frame = video.read()
    if not ok:
        print("Втрачено зв'язок з камерою.")
        break

    thresh_value = cv2.getTrackbarPos("Threshold", window_name)
    blur_value = cv2.getTrackbarPos("Blur (Odd)", window_name)

    if blur_value % 2 == 0:
        blur_value += 1
    if blur_value < 1:
        blur_value = 1

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (blur_value, blur_value), 0)
    _, thresh = cv2.threshold(blurred, thresh_value, 255, cv2.THRESH_BINARY_INV)

    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    cv2.drawContours(frame, contours, -1, (0, 255, 0), 2)

    cv2.putText(frame, f"Thresh: {thresh_value} | Blur: {blur_value}x{blur_value}", 
                (15, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
    cv2.putText(frame, f"Contours found: {len(contours)}", 
                (15, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 0), 1)

    cv2.imshow(window_name, frame)

    key = cv2.waitKey(1) & 0xFF
    if key == ord('q'):
        break
video.release()
cv2.destroyAllWindows()
print("Тест маски завершено.")