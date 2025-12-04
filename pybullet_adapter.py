"""
PyBullet Adapter for Robot-Collab
기존 robot-collab의 LLM 로직(Brain)과 사용자 정의 PyBullet 환경(Body)을 연결하는 어댑터입니다.

INTEGRATION_PLAN Phase 2 구현:
- 실제 Inverse Kinematics (IK) 제어
- PyBullet 모터 제어 루프
- Magic Grasp (Fixed Constraint)
"""
import time
import numpy as np
import pybullet as p

# 사용자님이 만드신 환경 임포트
from simulation_env import MultiRobotEnv

class PyBulletExecutor:
    """
    LLM이 생성한 High-level Plan(예: 'pick(apple)')을
    PyBullet Low-level Control로 변환하여 실행합니다.

    Phase 2: Real Physics Control 구현됨
    """
    def __init__(self, render=True, robot_config=None):
        """
        Initialize PyBullet executor.

        Args:
            render (bool): GUI mode
            robot_config (dict): Robot configuration to pass to MultiRobotEnv
                If None, uses default (KUKA + Panda)
        """
        # 1. Store config
        self.robot_config = robot_config

        # 2. Initialize environment with config
        self.env = MultiRobotEnv(gui=render, robot_config=robot_config)
        self.robot_ids = self.env.robot_ids
        self.object_map = self._build_object_name_map()

        # 3. Extract EE link indices from metadata
        self.ee_link_indices = self._extract_ee_links()

        # 4. Store robot metadata for IK
        self.robot_metadata = self.env.robot_metadata

        # 5. Grasp Constraint 저장용
        self.active_constraints = {}  # {robot_name: constraint_id}

        # 6. 비디오 녹화 관련
        self.is_recording = False
        self.video_log_id = None
        self.video_frames = []  # 프레임 버퍼
        self.video_output_path = None

        print("\n[Adapter] PyBullet Environment Connected.")
        print(f"[Adapter] Robots: {list(self.robot_ids.keys())}")

    def get_scene_description(self):
        """
        PyBullet 환경에서 Ground Truth TSD 생성

        Returns:
            str: 마크다운 형식의 현재 씬 상태 설명
        """
        tsd_lines = ["## Current Scene State\n"]

        # 1. 로봇 상태
        tsd_lines.append("### Robots")
        for robot_name, robot_id in self.robot_ids.items():
            ee_link = self.ee_link_indices[robot_name]
            ee_state = p.getLinkState(robot_id, ee_link)
            ee_pos = ee_state[0]

            display_name = "Robot_A (KUKA)" if robot_name == "kuka" else "Robot_B (Panda)"
            tsd_lines.append(f"- **{display_name}**")
            tsd_lines.append(f"  - End-Effector Position: ({ee_pos[0]:.3f}, {ee_pos[1]:.3f}, {ee_pos[2]:.3f})")

        # 2. 물체 상태
        tsd_lines.append("\n### Objects on Table")
        for obj_name, obj_id in self.object_map.items():
            pos, orn = p.getBasePositionAndOrientation(obj_id)
            tsd_lines.append(f"- **{obj_name}**: ({pos[0]:.3f}, {pos[1]:.3f}, {pos[2]:.3f})")

        tsd_lines.append("\n### Scene Context")
        tsd_lines.append("This is the current state of the simulation environment. ")
        tsd_lines.append("Use this information to generate appropriate task descriptions.")

        return "\n".join(tsd_lines)

    def start_video_recording(self, output_path="simulation_video.mp4", use_frame_capture=True):
        """
        비디오 녹화 시작

        Args:
            output_path: 출력 비디오 파일 경로
            use_frame_capture: True면 프레임 캡처 방식 (권장), False면 PyBullet 내장

        Returns:
            bool: 성공 여부
        """
        if self.is_recording:
            print("[Warning] Already recording, stopping previous recording first")
            self.stop_video_recording()

        self.video_output_path = output_path
        self.is_recording = True

        if use_frame_capture:
            # 프레임 캡처 방식 (안정적)
            self.video_frames = []
            print(f"[Video] Frame capture recording started: {output_path}")
            print(f"[Video] Using stable frame-by-frame capture method")
            return True
        else:
            # PyBullet 내장 방식 (불안정, RGB 깜빡임 발생 가능)
            try:
                self.video_log_id = p.startStateLogging(p.STATE_LOGGING_VIDEO_MP4, output_path)
                print(f"[Video] PyBullet logging started: {output_path}")
                print(f"[Warning] This method may cause RGB flickering")
                return True
            except Exception as e:
                print(f"[Warning] FFmpeg not available for MP4 recording: {e}")
                print(f"[Info] Continuing without video recording")
                print(f"[Info] To enable video: Install FFmpeg (see INSTALL_FFMPEG.md)")
                self.is_recording = False
                self.video_log_id = None
                return False

    def capture_frame(self):
        """
        현재 프레임을 캡처하여 버퍼에 저장 (녹화 중일 때만)
        """
        if not self.is_recording or self.video_frames is None:
            return

        try:
            # PyBullet 카메라로 이미지 캡처
            width, height = 1024, 768
            view_matrix = p.computeViewMatrixFromYawPitchRoll(
                cameraTargetPosition=[0, 0, 0.5],
                distance=2.5,
                yaw=45,
                pitch=-30,
                roll=0,
                upAxisIndex=2
            )
            proj_matrix = p.computeProjectionMatrixFOV(
                fov=60,
                aspect=width / height,
                nearVal=0.1,
                farVal=100.0
            )

            (_, _, px, _, _) = p.getCameraImage(
                width=width,
                height=height,
                viewMatrix=view_matrix,
                projectionMatrix=proj_matrix,
                renderer=p.ER_BULLET_HARDWARE_OPENGL
            )

            # RGB 이미지만 추출 (alpha 채널 제거)
            import numpy as np
            rgb_array = np.array(px, dtype=np.uint8)
            rgb_array = rgb_array[:, :, :3]  # RGBA -> RGB

            self.video_frames.append(rgb_array)
        except Exception as e:
            print(f"[Warning] Frame capture failed: {e}")

    def stop_video_recording(self):
        """
        비디오 녹화 중지 및 파일 저장

        Returns:
            bool: 성공 여부
        """
        if not self.is_recording:
            print("[Warning] No active recording to stop")
            return False

        # 프레임 캡처 방식
        if self.video_frames:
            try:
                print(f"[Video] Saving {len(self.video_frames)} frames to {self.video_output_path}")
                self._save_frames_to_video()
                self.video_frames = []
                self.is_recording = False
                print("[Video] Recording saved successfully")
                return True
            except Exception as e:
                print(f"[Error] Failed to save video: {e}")
                self.is_recording = False
                return False

        # PyBullet 내장 방식
        elif self.video_log_id is not None:
            try:
                p.stopStateLogging(self.video_log_id)
                self.is_recording = False
                self.video_log_id = None
                print("[Video] Recording stopped")
                return True
            except Exception as e:
                print(f"[Error] Failed to stop video recording: {e}")
                return False

        return False

    def _save_frames_to_video(self):
        """
        캡처된 프레임들을 MP4 파일로 저장
        """
        try:
            import cv2
            import numpy as np

            if not self.video_frames:
                print("[Warning] No frames to save")
                return

            # 비디오 설정
            height, width = self.video_frames[0].shape[:2]
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            fps = 30  # 30 FPS

            out = cv2.VideoWriter(
                self.video_output_path,
                fourcc,
                fps,
                (width, height)
            )

            # 프레임 쓰기
            for frame in self.video_frames:
                # RGB -> BGR (OpenCV 형식)
                bgr_frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                out.write(bgr_frame)

            out.release()
            print(f"[Video] Saved {len(self.video_frames)} frames at {fps} FPS")

        except ImportError:
            print("[Error] OpenCV (cv2) not installed. Cannot save video.")
            print("[Info] Install: pip install opencv-python")
        except Exception as e:
            print(f"[Error] Video save failed: {e}")

    def execute_plan(self, plan_text, record_video=False, video_path=None):
        """
        LLM이 생성한 텍스트 계획을 파싱하고 실행합니다.
        예: "robot_a.pick(apple)" -> PyBullet Pick 동작 수행

        Args:
            plan_text: 실행할 계획 텍스트
            record_video: 비디오 녹화 여부
            video_path: 비디오 출력 경로 (None이면 자동 생성)
        """
        print(f"\n[Executor] Received Plan: {plan_text}")

        # 비디오 녹화 시작
        if record_video:
            if video_path is None:
                import os
                from datetime import datetime

                # 출력 디렉토리 생성
                output_dir = os.path.join(os.path.dirname(__file__), "simulation_outputs", "videos")
                os.makedirs(output_dir, exist_ok=True)

                # 타임스탬프로 파일명 생성
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                video_path = os.path.join(output_dir, f"simulation_{timestamp}.mp4")
            else:
                # 사용자가 경로를 지정한 경우에도 simulation_outputs/videos/ 폴더로 저장
                import os
                output_dir = os.path.join(os.path.dirname(__file__), "simulation_outputs", "videos")
                os.makedirs(output_dir, exist_ok=True)

                # 파일명만 추출하여 출력 폴더에 저장
                video_filename = os.path.basename(video_path)
                video_path = os.path.join(output_dir, video_filename)

            self.start_video_recording(video_path)

        # 간단한 파싱 로직 (실제로는 더 복잡한 파서가 필요할 수 있음)
        # 예시 입력: "Robot_A picks apple" 또는 TDL 형태

        target_obj = None
        active_robot = None

        # 1. 대상 물체 식별
        plan_lower = plan_text.lower()
        for obj_name in self.object_map.keys():
            # Handle multi-word object names (e.g., "tuna_can" → "tuna can" or "tuna_can")
            if obj_name.replace('_', ' ') in plan_lower or obj_name in plan_lower:
                target_obj = obj_name
                break

        # 2. 수행 로봇 식별
        # simulation_env.py의 robot_ids는 'kuka'와 'panda'를 사용
        if "robot_b" in plan_text.lower() or "panda" in plan_text.lower():
            active_robot = "panda"
        else:
            active_robot = "kuka"  # Default KUKA (UR5e 역할)

        if target_obj:
            print(f"[Executor] Action: {active_robot} -> Pick -> {target_obj}")
            success = self._perform_pick(active_robot, target_obj)

            # 비디오 녹화 중지
            if record_video:
                self.stop_video_recording()

            result_msg = f"Picked {target_obj}"
            if record_video and success:
                result_msg += f" (Video: {video_path})"
            return success, result_msg
        else:
            print("[Executor] No valid object found in plan.")

            # 비디오 녹화 중지
            if record_video:
                self.stop_video_recording()

            return False, "Target object not found"

    def execute_action_sequence(self, action_sequence, record_video=False, video_path=None):
        """
        다중 액션 시퀀스를 순차적으로 실행합니다.

        Args:
            action_sequence: 액션 리스트 [{'action': 'pick', 'object': 'apple', 'robot': 'panda'}, ...]
            record_video: 비디오 녹화 여부
            video_path: 비디오 출력 경로 (None이면 자동 생성)

        Returns:
            (bool, str): (성공 여부, 결과 메시지)
        """
        print(f"\n[Executor] Received Action Sequence: {len(action_sequence)} actions")

        # 비디오 녹화 시작
        if record_video:
            if video_path is None:
                import os
                from datetime import datetime

                # 출력 디렉토리 생성
                output_dir = os.path.join(os.path.dirname(__file__), "simulation_outputs", "videos")
                os.makedirs(output_dir, exist_ok=True)

                # 타임스탬프로 파일명 생성
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                video_path = os.path.join(output_dir, f"simulation_{timestamp}.mp4")
            else:
                # 사용자가 경로를 지정한 경우에도 simulation_outputs/videos/ 폴더로 저장
                import os
                output_dir = os.path.join(os.path.dirname(__file__), "simulation_outputs", "videos")
                os.makedirs(output_dir, exist_ok=True)

                # 파일명만 추출하여 출력 폴더에 저장
                video_filename = os.path.basename(video_path)
                video_path = os.path.join(output_dir, video_filename)

            self.start_video_recording(video_path)

        # 액션 시퀀스 순차 실행
        completed_actions = []
        for i, action_dict in enumerate(action_sequence, 1):
            action_type = action_dict.get('action', 'pick')
            obj_name = action_dict.get('object', 'apple')
            robot_name = action_dict.get('robot', 'panda')

            # 로봇 이름 매핑 (master_pipeline의 internal_robot_key → pybullet robot_id)
            robot_map = {
                'panda': 'panda',
                'ur5e': 'kuka',  # UR5e는 KUKA로 매핑
                'kuka_iiwa14': 'kuka',
                'doosan_m0609': 'panda',  # Fallback
                'doosan_m1013': 'panda',
                'doosan_h2515': 'panda'
            }
            active_robot = robot_map.get(robot_name, 'panda')

            print(f"\n[Executor] Action {i}/{len(action_sequence)}: {active_robot} {action_type} {obj_name}")

            # 액션 타입에 따라 실행
            if action_type == 'pick':
                success = self._perform_pick(active_robot, obj_name)
                if not success:
                    error_msg = f"Failed at action {i}: pick {obj_name}"
                    print(f"[ERROR] {error_msg}")
                    if record_video:
                        self.stop_video_recording()
                    return False, error_msg
                completed_actions.append(f"pick {obj_name}")

            elif action_type == 'place':
                success = self._perform_place(active_robot, obj_name)
                if not success:
                    error_msg = f"Failed at action {i}: place {obj_name}"
                    print(f"[ERROR] {error_msg}")
                    if record_video:
                        self.stop_video_recording()
                    return False, error_msg
                completed_actions.append(f"place {obj_name}")

            else:
                print(f"[WARNING] Unknown action type: {action_type}")
                continue

        # 마지막 액션 완료 후 홀딩 프레임 추가 (final pose 녹화)
        if record_video:
            print(f"  > Capturing final frames...")
            for _ in range(30):  # 1초 분량 (30 FPS 기준)
                self.env.step()
                self.capture_frame()

        # 비디오 녹화 중지
        if record_video:
            self.stop_video_recording()

        # 성공 메시지
        result_msg = f"Completed {len(completed_actions)} actions: {' → '.join(completed_actions)}"
        if record_video:
            result_msg += f" (Video: {video_path})"

        print(f"\n[OK] Action sequence completed successfully!")
        return True, result_msg

    def _build_object_name_map(self):
        """
        물체 이름 → PyBullet ID 매핑 생성
        """
        obj_map = {}
        for obj_id, obj_meta in self.env.objects.items():
            obj_map[obj_meta['name']] = obj_id
        return obj_map

    def _extract_ee_links(self):
        """
        Extract end-effector link indices from robot metadata.

        Returns:
            dict: {robot_id: ee_link_index}
        """
        ee_links = {}

        for robot_key in self.robot_ids.keys():
            metadata = self.env.robot_metadata[robot_key]
            ee_link = metadata['config']['ee_link_index']
            ee_links[robot_key] = ee_link
            print(f"  [Adapter] {robot_key} EE Link Index: {ee_link}")

        return ee_links

    def move_to_pose(self, robot_name, target_pos, target_orn=None, max_steps=2000, error_threshold=0.02):
        """
        로봇을 목표 위치로 이동 (Real IK + Motor Control)

        Args:
            robot_name: 로봇 이름 (e.g., 'kuka', 'panda')
            target_pos: 목표 위치 [x, y, z]
            target_orn: 목표 방향 (quaternion), None이면 현재 방향 유지
            max_steps: 최대 시뮬레이션 스텝 수
            error_threshold: 목표 도달 판단 임계값 (m)

        Returns:
            bool: 성공 여부
        """
        robot_id = self.robot_ids[robot_name]
        ee_link = self.ee_link_indices[robot_name]
        metadata = self.robot_metadata[robot_name]

        # 기본 방향 설정 (downward grasp)
        if target_orn is None:
            target_orn = p.getQuaternionFromEuler([np.pi, 0, 0])

        # 1. IK 계산 with joint limits from metadata
        joint_limits = metadata['config'].get('joint_limits', {})

        joint_poses = p.calculateInverseKinematics(
            robot_id,
            ee_link,
            target_pos,
            target_orn,
            lowerLimits=joint_limits.get('lower'),
            upperLimits=joint_limits.get('upper'),
            jointRanges=joint_limits.get('ranges'),
            restPoses=joint_limits.get('rest_poses'),
            maxNumIterations=200,
            residualThreshold=1e-4
        )

        # 2. 모터 제어로 조인트 이동 (controllable_joints만)
        controllable_joints = metadata['config']['controllable_joints']

        for i in range(controllable_joints):
            p.setJointMotorControl2(
                robot_id,
                i,
                p.POSITION_CONTROL,
                targetPosition=joint_poses[i],
                force=500,
                maxVelocity=2.0  # Increased velocity
            )

        # 3. 시뮬레이션 스텝 실행 (도달할 때까지)
        min_error = float('inf')
        stuck_counter = 0

        for step in range(max_steps):
            self.env.step()

            # 비디오 녹화 중이면 프레임 캡처 (매 5 스텝마다)
            if self.is_recording and step % 5 == 0:
                self.capture_frame()

            # 현재 EE 위치 확인
            link_state = p.getLinkState(robot_id, ee_link)
            current_pos = link_state[4]  # World position

            # 목표 도달 체크
            error = np.linalg.norm(np.array(target_pos) - np.array(current_pos))

            # Track minimum error
            if error < min_error:
                min_error = error
                stuck_counter = 0
            else:
                stuck_counter += 1

            # Success condition
            if error < error_threshold:
                print(f"  > Reached target (error: {error:.4f}m in {step} steps)")
                return True

            # Early exit if stuck (error not improving for 200 steps)
            if stuck_counter > 200:
                print(f"  [Warning] {robot_name} stuck at error {min_error:.4f}m")
                if min_error < error_threshold * 2:  # Accept if within 2x threshold
                    print(f"  > Accepting approximate position")
                    return True
                return False

            if step % 100 == 0 and step > 0:
                print(f"  > Step {step}/{max_steps}, error: {error:.4f}m")

            time.sleep(1./240.)  # Real-time simulation

        print(f"  [Warning] {robot_name} timeout. Final error: {min_error:.4f}m")
        # Accept if close enough
        if min_error < error_threshold * 1.5:
            print(f"  > Accepting final position")
            return True

        return False

    def _grasp_object(self, robot_name, obj_name):
        """
        Magic Grasp: Create fixed constraint between gripper and object
        """
        robot_id = self.robot_ids[robot_name]
        obj_id = self.object_map[obj_name]
        ee_link = self.ee_link_indices[robot_name]
        metadata = self.robot_metadata[robot_name]

        # 그리퍼 닫기 (gripper_joints가 있는 로봇만)
        gripper_joints = metadata['config'].get('gripper_joints', [])
        if gripper_joints:
            for gripper_joint in gripper_joints:
                p.setJointMotorControl2(
                    robot_id,
                    gripper_joint,
                    p.POSITION_CONTROL,
                    targetPosition=0.0,  # 닫힘
                    force=100
                )

            # 그리퍼 닫히는 동안 대기
            for _ in range(50):
                self.env.step()
                time.sleep(1./240.)

        # Magic Grasp: Fixed Constraint 생성
        constraint_id = p.createConstraint(
            robot_id,
            ee_link,
            obj_id,
            -1,  # Base link of object
            p.JOINT_FIXED,
            [0, 0, 0],
            [0, 0, 0],
            [0, 0, 0]
        )

        self.active_constraints[robot_name] = constraint_id
        print(f"  > Grasped {obj_name} (Constraint ID: {constraint_id})")

        return True

    def _release_object(self, robot_name):
        """
        Release grasped object by removing constraint
        """
        if robot_name in self.active_constraints:
            p.removeConstraint(self.active_constraints[robot_name])
            del self.active_constraints[robot_name]

            # Open gripper dynamically from metadata
            metadata = self.robot_metadata[robot_name]
            gripper_joints = metadata['config'].get('gripper_joints', [])

            if gripper_joints:
                robot_id = self.robot_ids[robot_name]
                for gripper_joint in gripper_joints:
                    p.setJointMotorControl2(
                        robot_id,
                        gripper_joint,
                        p.POSITION_CONTROL,
                        targetPosition=0.04,  # Open
                        force=100
                    )

                # Wait for gripper to open
                for _ in range(50):
                    self.env.step()

            print(f"  > Released object")
            return True
        return False

    def _perform_pick(self, robot_name, obj_name):
        """
        PyBullet에서 실제 픽 동작을 수행 (Real Physics Control)
        """
        robot_id = self.robot_ids[robot_name]
        obj_id = self.object_map[obj_name]

        # 1. 물체 위치 가져오기
        obj_info = self.env.get_object_info(obj_id)
        target_pos = obj_info['position']
        print(f"  > Target Position: {target_pos}")

        # 2. 접근 (Move to Hover) - 물체 위 20cm
        hover_pos = [target_pos[0], target_pos[1], target_pos[2] + 0.2]
        print(f"  > Moving {robot_name} to hover position...")
        success = self.move_to_pose(robot_name, hover_pos)
        if not success:
            print(f"  [ERROR] Failed to reach hover position")
            return False

        # 3. 하강 (Move to Object)
        grasp_pos = [target_pos[0], target_pos[1], target_pos[2] + 0.05]  # 물체 위 5cm
        print(f"  > Descending to object...")
        success = self.move_to_pose(robot_name, grasp_pos)
        if not success:
            print(f"  [ERROR] Failed to reach grasp position")
            return False

        # 4. 잡기 (Magic Grasp)
        print(f"  > Grasping {obj_name}...")
        self._grasp_object(robot_name, obj_name)

        # Capture frames during grasp (simulate holding)
        for _ in range(10):
            self.env.step()
            self.capture_frame()

        # 5. 들어올리기 (Lift)
        lift_pos = [target_pos[0], target_pos[1], target_pos[2] + 0.3]
        print(f"  > Lifting...")
        success = self.move_to_pose(robot_name, lift_pos)
        if not success:
            print(f"  [ERROR] Failed to lift object")
            return False

        print(f"  > Pick operation completed successfully!")
        return True

    def _perform_place(self, robot_name, obj_name):
        """
        PyBullet에서 실제 플레이스 동작을 수행 (Release Object at Current Position)

        Args:
            robot_name: 로봇 이름 ('panda', 'kuka' 등)
            obj_name: 물체 이름 (현재 잡고 있는 물체)

        Returns:
            bool: 성공 여부
        """
        print(f"  > Placing {obj_name}...")

        # 1. 현재 end-effector 위치 가져오기
        robot_id = self.robot_ids[robot_name]
        ee_link = self.ee_link_indices[robot_name]

        import pybullet as p
        link_state = p.getLinkState(robot_id, ee_link)
        current_pos = link_state[4]  # World position of end-effector

        # 2. Place 위치 계산 (현재 위치에서 약간 아래로)
        place_pos = [current_pos[0], current_pos[1], current_pos[2] - 0.15]
        print(f"  > Moving to place position: {place_pos}")

        success = self.move_to_pose(robot_name, place_pos)
        if not success:
            print(f"  [ERROR] Failed to reach place position")
            return False

        # 3. 물체 놓기 (Release)
        print(f"  > Releasing {obj_name}...")
        self._release_object(robot_name)

        # Capture frames during release (show object falling)
        for _ in range(10):
            self.env.step()
            self.capture_frame()

        # 4. 로봇 후퇴 (Retract)
        retract_pos = [place_pos[0], place_pos[1], place_pos[2] + 0.2]
        print(f"  > Retracting...")
        success = self.move_to_pose(robot_name, retract_pos)
        if not success:
            print(f"  [WARNING] Failed to retract cleanly, but place succeeded")

        print(f"  > Place operation completed successfully!")
        return True

# --- 테스트 실행 코드 ---
if __name__ == "__main__":
    # 1. 기존의 Prompting 모듈 등을 여기서 불러올 수 있음
    # from prompting.dialog_prompter import DialogPrompter (파일 경로 확인 필요)
    
    # 2. 어댑터 실행
    executor = PyBulletExecutor(render=True)
    
    # 3. 가상의 LLM 출력 상황 시뮬레이션
    test_commands = [
        "Robot_A, please pick the apple.",
        "Now, Robot_B should pick the banana."
    ]
    
    for cmd in test_commands:
        print(f"\n--- Processing Command: \"{cmd}\" ---")
        executor.execute_plan(cmd)
        time.sleep(1)
        
    print("\n[Test] Integration Test Complete.")