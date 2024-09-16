import cv2
import mediapipe as mp
import time
import numpy as np
import redis  # Redis 모듈 추가

# Mediapipe 솔루션 초기화
mp_face_mesh = mp.solutions.face_mesh
mp_drawing = mp.solutions.drawing_utils

# 카메라 사용
cap = cv2.VideoCapture(0)
if not cap.isOpened():
    print("카메라를 찾을 수 없습니다.")
    exit()

# Redis 클라이언트 초기화
redis_client = redis.Redis(host='localhost', port=6379, db=0)

previous_direction = None  # 이전 방향 저장 변수

# Mediapipe 얼굴 메쉬 설정
with mp_face_mesh.FaceMesh(
    max_num_faces=1,  # 감지할 최대 얼굴 수
    refine_landmarks=True,  # 세부 랜드마크 사용
    min_detection_confidence=0.5,
    min_tracking_confidence=0.5
) as face_mesh:

    eye_blink_start_time = None  # 눈을 감은 시점
    eye_blink_threshold = 0.007  # 눈이 감겼는지 판단할 임계값
    blink_duration = 0.5  # 눈이 감긴 상태를 감지할 지속 시간 (초)

    while cap.isOpened():
        success, image = cap.read()
        if not success:
            print("카메라를 찾을 수 없습니다.")
            break

        image = cv2.cvtColor(cv2.flip(image, 1), cv2.COLOR_BGR2RGB)
        image.flags.writeable = False
        results = face_mesh.process(image)

        image.flags.writeable = True
        image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)

        direction = "none"  # 방향 초기화
        yaw = None  # yaw 초기화

        if results.multi_face_landmarks:
            for face_landmarks in results.multi_face_landmarks:
                try:
                    # 주요 랜드마크 추출
                    left_eye_outer = face_landmarks.landmark[33]   # 왼쪽 눈 바깥
                    right_eye_outer = face_landmarks.landmark[263] # 오른쪽 눈 바깥
                    nose_tip = face_landmarks.landmark[1]          # 코 끝
                    left_eye_upper = face_landmarks.landmark[159]  # 왼쪽 눈 위
                    left_eye_lower = face_landmarks.landmark[145]  # 왼쪽 눈 아래

                    # 3D 좌표 변환
                    h, w, _ = image.shape
                    left_eye = np.array([left_eye_outer.x * w, left_eye_outer.y * h, left_eye_outer.z * w])
                    right_eye = np.array([right_eye_outer.x * w, right_eye_outer.y * h, right_eye_outer.z * w])
                    nose = np.array([nose_tip.x * w, nose_tip.y * h, nose_tip.z * w])

                    left_eye_coord = (int(left_eye_outer.x * w), int(left_eye_outer.y * h))
                    right_eye_coord = (int(right_eye_outer.x * w), int(right_eye_outer.y * h))
                    nose_tip_coord = (int(nose_tip.x * w), int(nose_tip.y * h))

                    # 랜드마크 표시
                    cv2.circle(image, left_eye_coord, 3, (0, 255, 0), -1)  # 초록색 원
                    cv2.circle(image, right_eye_coord, 3, (255, 0, 0), -1)  # 파란색 원
                    cv2.circle(image, nose_tip_coord, 3, (0, 0, 255), -1)  # 빨간색 원

                    # 얼굴 중심 계산 (두 눈의 중간 지점)
                    face_center = (left_eye + right_eye) / 2
                    center_x = int((left_eye_outer.x + right_eye_outer.x) / 2 * w)

                    # 얼굴의 회전 벡터 계산
                    face_vector = nose - face_center
                    face_vector /= np.linalg.norm(face_vector)  # 정규화

                    # 얼굴 회전 각도 계산 (Yaw)
                    yaw = np.arctan2(face_vector[0], face_vector[2]) * 180 / np.pi

                    # 왼쪽 눈 감김 계산
                    left_eye_dist = abs(left_eye_upper.y * h - left_eye_lower.y * h)

                    # 눈 깜빡임 감지
                    if left_eye_dist < eye_blink_threshold * h:
                        if eye_blink_start_time is None:
                            eye_blink_start_time = time.time()
                        elif time.time() - eye_blink_start_time >= blink_duration:
                            direction = "stop"
                    else:
                        eye_blink_start_time = None

                    # 얼굴 방향 결정 (Yaw를 기준으로 설정)
                    if direction not in ["stop", "unknown"]:
                        if yaw <= -160 or yaw >= 160:
                            direction = "front"
                        elif yaw < 0:
                            if yaw > -115:
                                direction = "left++"
                            elif yaw > -145:
                                direction = "left+"
                            elif yaw > -160:
                                direction = "left"
                        else:
                            if yaw < 115:
                                direction = "right++"
                            elif yaw < 145:
                                direction = "right+"
                            elif yaw < 160:
                                direction = "right"

                except (IndexError, AttributeError):
                    direction = "unknown"
        else:
            direction = "unknown"

        # 방향 정보 구성
        if yaw is not None:
            new_direction = f'{direction}  Yaw: {int(yaw)}'
        else:
            new_direction = direction

        # 방향 정보가 변경되었을 때만 Redis에 발행
        if new_direction != previous_direction:
            redis_client.publish('direction_channel', new_direction)
            previous_direction = new_direction

        # 방향 및 각도 텍스트 표시
        cv2.putText(image, new_direction,
                    (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 0, 0), 2, cv2.LINE_AA)

        # 화면 출력
        cv2.imshow('MediaPipe Face Mesh', image)
        if cv2.waitKey(5) & 0xFF == 27:
            break

# 자원 해제
cap.release()
cv2.destroyAllWindows()