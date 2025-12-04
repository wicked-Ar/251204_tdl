"""
Master Pipeline - Complete NL2TDL2Validation Pipeline

자연어 → TDL v1 → 로봇 선택 → 동역학 검증 → TDL v2 → 시뮬레이션 검증

전체 파이프라인:
1. Ground Truth TSD (선택) - MuJoCo Observation → Textual State Description
2. NL → TDL v1 (Gemini LLM + TSD context)
3. Robot Selection - 최적 로봇 선택
4. Dynamics Validation - 물리적 실현가능성 검증
5. TDL v2 생성 - 로봇별 실제 파라미터
6. Simulation Validation (validation_integration) - Roco 시뮬레이션 + 비디오
"""

import sys
import os
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional, List

# 경로 설정
CURRENT_DIR = Path(__file__).parent
sys.path.insert(0, str(CURRENT_DIR))

# TDL Action Parser 임포트
from tdl_action_parser import TDLActionParser

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class MasterPipeline:
    """
    NL2TDL 완전 통합 파이프라인

    자연어 명령을 받아 TDL 생성, 검증, 시뮬레이션 실행까지 전체 과정 수행
    """

    def __init__(self, use_tsd: bool = True, api_key: str = None):
        """
        Args:
            use_tsd: Ground Truth TSD 생성 사용 여부 (기본: True)
            api_key: Gemini API 키 (선택)
        """
        print("=" * 80)
        print(" NL2TDL Master Pipeline - Initializing")
        print("=" * 80)

        self.use_tsd = use_tsd
        self.history = []

        # 0. TDL Action Parser (다중 액션 추출)
        print("\n[0/5] Initializing TDL Action Parser...")
        self.tdl_parser = TDLActionParser()

        # 1. NL2TDL Converter
        print("[1/5] Loading NL2TDL Converter...")
        from TDL_generation.nl2tdl_converter import NL2TDLConverter
        self.nl2tdl = NL2TDLConverter(api_key=api_key)

        # 2. TSD Generator (Ground Truth State Description)
        if use_tsd:
            print("[2/5] Loading Ground Truth TSD Generator...")
            from TDL_generation.state_to_text_generator import StateToTextGenerator
            self.tsd_generator = StateToTextGenerator()
        else:
            print("[2/5] TSD disabled (using NL only)")
            self.tsd_generator = None

        # 3. Robot Selector
        print("[3/5] Loading Robot Selector...")
        from robot_selection.robot_selector import select_best_robot
        self.select_robot_func = select_best_robot

        # Load robot database for dynamics profile lookup
        import json
        db_path = os.path.join(
            os.path.dirname(__file__),
            'robot_selection', 'data', 'robot_db.json'
        )
        with open(db_path, 'r', encoding='utf-8') as f:
            self.robot_db = json.load(f)

        # 4. Dynamics Validator
        print("[4/5] Loading Dynamics Validator...")
        from dynamics_validation.parameter_scaler import ParameterScaler
        from dynamics_validation.robot_dynamics_db import load_robot

        # 로봇 DB는 나중에 로봇 선택 후 로드
        self.dynamics_validator = None

        # 5. Simulation Validator (PyBullet)
        # 시뮬레이터는 로봇 선택 후 초기화
        print("[5/5] Deferring Simulator initialization until robot selection...")
        self.sim_validator = None

        print("\n[OK] Master Pipeline Ready!")
        print("  (Simulator will be initialized after robot selection)")
        print("=" * 80)

    def execute_full_pipeline(self,
                            user_nl: str,
                            robot_requirements: Dict = None,
                            output_video: str = None,
                            enable_dynamics: bool = True) -> Dict:
        """
        전체 파이프라인 실행

        Args:
            user_nl: 사용자 자연어 명령
            robot_requirements: 로봇 요구사항 (선택)
            output_video: 출력 비디오 경로 (기본값: auto)
            enable_dynamics: 동역학 검증 활성화 여부

        Returns:
            dict: 전체 실행 결과
        """
        print("\n" + "=" * 80)
        print(f" Executing Pipeline: \"{user_nl}\"")
        print("=" * 80)

        result = {
            'user_nl': user_nl,
            'timestamp': datetime.now().isoformat(),
            'success': False
        }

        # Step 1: NL → TDL v1 (without TSD context initially)
        print("\n" + "-" * 80)
        print(" STEP 1: NL → TDL v1 Generation (Initial)")
        print("-" * 80)

        try:
            tdl_result = self.nl2tdl.convert_with_metadata(user_nl)

            # convert_with_metadata returns {'tdl_code': ..., 'metadata': ...}
            if 'tdl_code' not in tdl_result:
                result['error'] = "TDL generation failed: No TDL code returned"
                return result

            tdl_v1 = tdl_result['tdl_code']
            print(f"[OK] TDL v1 generated ({len(tdl_v1)} chars)")
            result['tdl_v1'] = tdl_v1

            # TDL 파일 저장
            try:
                output_dir = Path(CURRENT_DIR) / "TDL_generation" / "output"
                output_dir.mkdir(parents=True, exist_ok=True)

                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                tdl_filename = f"tdl_v1_{timestamp}.txt"
                tdl_filepath = output_dir / tdl_filename

                with open(tdl_filepath, 'w', encoding='utf-8') as f:
                    f.write(f"# Generated TDL v1\n")
                    f.write(f"# Timestamp: {datetime.now().isoformat()}\n")
                    f.write(f"# User Command: {user_nl}\n")
                    f.write(f"# {'='*60}\n\n")
                    f.write(tdl_v1)

                print(f"  TDL saved to: {tdl_filepath}")
                result['tdl_filepath'] = str(tdl_filepath)
            except Exception as e:
                logger.warning(f"Failed to save TDL file: {e}")

        except Exception as e:
            result['error'] = f"TDL generation error: {e}"
            logger.exception("TDL generation failed")
            return result

        # Step 2: Robot Selection
        print("\n" + "-" * 80)
        print(" STEP 2: Robot Selection")
        print("-" * 80)

        try:
            # select_best_robot returns Tuple[str, float, Dict]
            robot_id, confidence, all_scores = self.select_robot_func(
                tdl_v1_content=tdl_v1,
                robot_db_path=None,
                weights=robot_requirements if robot_requirements else None
            )

            # Build robot_result structure
            robot_result = {
                'selected_robot': {
                    'id': robot_id,
                    'name': robot_id,
                    'confidence': confidence
                },
                'reason': f"Selected with confidence {confidence:.2f}",
                'all_scores': all_scores
            }

            selected_robot = robot_result['selected_robot']
            print(f"[OK] Selected Robot: {selected_robot['name']}")
            print(f"  Confidence: {confidence:.2f}")
            print(f"  Reason: {robot_result['reason']}")
            result['robot_selection'] = robot_result

        except Exception as e:
            result['error'] = f"Robot selection error: {e}"
            logger.exception("Robot selection failed")
            return result

        # Step 3: Initialize Simulator with Selected Robot
        print("\n" + "-" * 80)
        print(" STEP 3: Initialize Simulator with Selected Robot")
        print("-" * 80)

        try:
            # Build robot configuration
            robot_config = self._build_robot_config(robot_id)
            print(f"  Robot_A: {robot_config['Robot_A']['robot_id']}")
            print(f"  Robot_B: {robot_config['Robot_B']['robot_id']}")

            # Initialize simulator
            self._initialize_simulator(robot_config)

        except Exception as e:
            result['error'] = f"Simulator initialization error: {e}"
            logger.exception("Simulator initialization failed")
            return result

        # Step 4: Ground Truth TSD Generation (optional, after robot selection)
        scene_context = None
        if self.use_tsd and self.tsd_generator:
            print("\n" + "-" * 80)
            print(" STEP 4: Ground Truth TSD Generation")
            print("-" * 80)

            try:
                # PyBullet scene description from initialized simulator
                scene_context = self.sim_validator.get_scene_description()

                # Store result
                result['tsd_analysis'] = {'context': scene_context}
                print("[OK] TSD context generated from PyBullet scene")
                print(f"\n{scene_context}\n")

            except Exception as e:
                print(f"[X] TSD generation error: {e}")
                logger.exception("TSD generation failed")
                scene_context = None

        # Step 5: Dynamics Validation (optional)
        tdl_v2 = None
        if enable_dynamics:
            print("\n" + "-" * 80)
            print(" STEP 5: Dynamics Validation")
            print("-" * 80)

            try:
                from dynamics_validation.parameter_scaler import ParameterScaler
                from dynamics_validation.robot_dynamics_db import load_robot

                # Get selected robot spec to access dynamics_profile
                selected_robot_id = selected_robot['id']
                selected_spec = self.robot_db.get(selected_robot_id)

                if not selected_spec:
                    raise ValueError(f"Robot '{selected_robot_id}' not found in database")

                # Use dynamics_profile to load correct dynamics
                dynamics_name = selected_spec.get('dynamics_profile', 'Robot_A')

                print(f"[Dynamics Validation]")
                print(f"  Selected Robot: {selected_robot_id}")
                print(f"  Dynamics Profile: {dynamics_name}")

                robot_db = load_robot(robot_name=dynamics_name)
                print(f"  Loaded dynamics for {dynamics_name} (validating {selected_robot_id})")

                # 동역학 검증
                scaler = ParameterScaler(robot_db, safety_margin=0.9)

                # TDL v1에서 파라미터 추출 (간단한 예시)
                tdl_params = self._extract_tdl_parameters(tdl_v1)

                scaling_result = scaler.scale_tdl_parameters(tdl_params)

                print(f"[OK] Dynamics validation complete")
                print(f"  Feasible: {scaling_result['feasible']}")
                print(f"  Scale Factor: {scaling_result['scale_factor']:.3f}")

                result['dynamics_validation'] = scaling_result
                tdl_v2 = scaling_result['tdl_v2']

            except Exception as e:
                print(f"[!] Dynamics validation skipped: {e}")
                logger.warning("Dynamics validation failed, continuing without it")
                tdl_v2 = None

        # Step 6: Simulation Validation (PyBullet)
        print("\n" + "-" * 80)
        print(" STEP 6: Simulation Validation (PyBullet)")
        print("-" * 80)

        try:
            # Map robot selector ID to internal robot key
            # Since we loaded the selected robot into Robot_A slot, use that
            robot_to_internal_key = {
                'panda': 'panda',
                'kuka_iiwa14': 'kuka_iiwa14',
                'ur5e': 'ur5e',
                'doosan_m0609': 'doosan_m0609',
                'doosan_m1013': 'doosan_m1013',
                'doosan_h2515': 'doosan_h2515',
            }

            internal_robot_key = robot_to_internal_key.get(robot_id, robot_id)
            print(f"  Using robot: {internal_robot_key}")

            # TDL v1에서 액션 시퀀스 추출 (다중 액션 지원)
            action_sequence = self._tdl_to_action_sequence(tdl_v1, internal_robot_key)

            if not action_sequence:
                print("[WARNING] No actions extracted from TDL. Falling back to single action.")
                tdl_dict = self._tdl_to_dict(tdl_v1, internal_robot_key, user_nl)
                action_sequence = [tdl_dict]

            # PyBullet 실행 계획 생성 (요약)
            plan_summary = " → ".join([f"{a['action']} {a['object']}" for a in action_sequence])
            print(f"  Generated plan: {internal_robot_key}: {plan_summary}")

            # 비디오 파일명 생성 (실제 경로는 simulation_outputs/videos/에 자동 저장됨)
            if output_video is None:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                output_video = f"simulation_{timestamp}.mp4"

            # PyBullet 실행 (비디오 녹화 포함, 다중 액션 지원)
            # Note: 비디오는 자동으로 simulation_outputs/videos/ 폴더에 저장됨
            success, message = self.sim_validator.execute_action_sequence(
                action_sequence,
                record_video=True,
                video_path=output_video
            )

            if success:
                print(f"\n[OK] Simulation validation SUCCESS!")
                print(f"  Message: {message}")
                print(f"  Video saved: {output_video}")

                result['success'] = True
                result['simulation'] = {
                    'success': True,
                    'message': message,
                    'plan': plan_summary,
                    'action_sequence': action_sequence,
                    'video_path': output_video
                }
            else:
                print(f"\n[X] Simulation validation FAILED")
                print(f"  Error: {message}")

                result['error'] = f"Simulation failed: {message}"
                result['simulation'] = {
                    'success': False,
                    'error': message,
                    'plan': plan_summary,
                    'action_sequence': action_sequence
                }

        except Exception as e:
            result['error'] = f"Simulation error: {e}"
            logger.exception("Simulation validation failed")
            return result

        # 히스토리 저장
        self.history.append(result)

        return result

    def _build_robot_config(self, robot_id: str) -> Dict:
        """
        Convert robot selection result to robot_config for simulator.

        Args:
            robot_id: Selected robot ID from robot selection (e.g., 'panda', 'kuka_iiwa14')

        Returns:
            dict: Robot configuration for MultiRobotEnv
                {
                    'Robot_A': {robot_db entry with pybullet_config},
                    'Robot_B': {robot_db entry with pybullet_config}
                }
        """
        import json

        # Load robot database
        db_path = os.path.join(
            os.path.dirname(__file__),
            'robot_selection', 'data', 'robot_db.json'
        )

        with open(db_path, 'r', encoding='utf-8') as f:
            robot_db = json.load(f)

        # Validate selected robot has URDF
        if robot_id not in robot_db:
            raise ValueError(f"Robot '{robot_id}' not found in robot database")

        selected_robot_spec = robot_db[robot_id]
        pybullet_cfg = selected_robot_spec.get('pybullet_config', {})

        if not pybullet_cfg.get('urdf_available', False):
            error_msg = pybullet_cfg.get(
                'error_message',
                f"URDF not available for {robot_id}"
            )
            raise ValueError(
                f"[ERROR] Cannot simulate with {robot_id}: {error_msg}\n"
                f"Available robots: panda, kuka_iiwa14"
            )

        # Build 2-slot configuration
        # Robot_A: Selected robot
        # Robot_B: Panda (for future multi-robot scenarios)
        robot_config = {
            'Robot_A': selected_robot_spec,
            'Robot_B': robot_db['panda']  # Always load Panda as second robot
        }

        return robot_config

    def _initialize_simulator(self, robot_config: Dict) -> None:
        """
        Initialize PyBullet simulator with selected robot configuration.

        Args:
            robot_config: Robot configuration from _build_robot_config()
        """
        print("\n[*] Initializing PyBullet simulator with selected robot configuration...")

        from pybullet_adapter import PyBulletExecutor
        self.sim_validator = PyBulletExecutor(render=True, robot_config=robot_config)

        print("[OK] Simulator initialized with dynamic robot configuration")

    def _extract_tdl_parameters(self, tdl_code: str) -> Dict:
        """
        TDL 코드에서 파라미터 추출 (간단한 파서)

        실제로는 더 정교한 파싱이 필요하지만, 여기서는 간단히 구현
        """
        # 기본값
        params = {
            'task': 'pick',
            'accel_percent': 50,
            'speed_percent': 50
        }

        # TDL에서 숫자 추출 시도
        import re

        # 속도/가속도 파라미터 찾기
        velocity_match = re.search(r'velocity[:\s]+(\d+)', tdl_code, re.IGNORECASE)
        if velocity_match:
            params['speed_percent'] = int(velocity_match.group(1))

        accel_match = re.search(r'accel[eration]*[:\s]+(\d+)', tdl_code, re.IGNORECASE)
        if accel_match:
            params['accel_percent'] = int(accel_match.group(1))

        return params

    def _tdl_to_action_sequence(self, tdl_code: str, robot_name: str) -> List[Dict]:
        """
        TDL 코드에서 액션 시퀀스 추출 (다중 액션 지원)

        Args:
            tdl_code: TDL 코드 (LLM 생성)
            robot_name: 로봇 이름

        Returns:
            액션 시퀀스 리스트: [{'action': 'pick', 'object': 'apple', 'robot': 'panda'}, ...]
        """
        print("\n[TDL Parser] Extracting action sequence from TDL...")

        # TDL 파서로 액션 추출
        actions = self.tdl_parser.parse_tdl_to_actions(tdl_code)

        # 각 액션에 로봇 정보 추가
        for action in actions:
            action['robot'] = robot_name
            action['speed'] = 50  # 기본 속도

        action_summary = [f"{a['action']} {a['object']}" for a in actions]
        print(f"[TDL Parser] Extracted {len(actions)} actions: {action_summary}")

        return actions

    def _tdl_to_dict(self, tdl_code: str, robot_name: str, user_nl: str = "") -> Dict:
        """
        TDL 코드를 validation_integration이 기대하는 딕셔너리 형식으로 변환

        Args:
            tdl_code: TDL 코드 (LLM 생성 또는 fallback)
            robot_name: 로봇 이름
            user_nl: 원본 자연어 명령 (fallback용)

        Returns:
            TDL 딕셔너리
        """
        import re

        # 기본 TDL 딕셔너리
        tdl_dict = {
            'task': 'pick',
            'object': 'apple',
            'robot': robot_name,
            'speed': 50
        }

        # TDL 코드에서 정보 추출
        # Pick, Place, Move 등 찾기
        search_text = tdl_code.lower()
        if 'pick' in search_text:
            tdl_dict['task'] = 'pick'
        elif 'place' in search_text:
            tdl_dict['task'] = 'place'
            tdl_dict['location'] = 'bin'  # 기본값
        elif 'move' in search_text:
            tdl_dict['task'] = 'move'
            tdl_dict['location'] = 'home'
        elif 'inspect' in search_text:
            tdl_dict['task'] = 'inspect'

        # 물체 이름 추출 - 우선순위:
        # 1. TDL 코드에서 찾기
        # 2. 원본 NL에서 찾기 (TDL 생성 실패 시)
        # 3. TSD context에서 찾기 (환경에 있는 물체)
        objects = ['apple', 'banana', 'milk', 'bread', 'soda', 'part']

        # 1. TDL 코드에서 찾기
        found = False
        for obj in objects:
            if obj in search_text:
                tdl_dict['object'] = obj
                found = True
                break

        # 2. TDL에서 못 찾았으면 원본 NL에서 찾기
        if not found and user_nl:
            nl_lower = user_nl.lower()
            for obj in objects:
                if obj in nl_lower:
                    tdl_dict['object'] = obj
                    print(f"  [Fallback] Object '{obj}' extracted from NL command")
                    found = True
                    break

        # 3. 여전히 못 찾았으면 경고 출력
        if not found:
            print(f"  [WARNING] No object found in TDL or NL. Using default: {tdl_dict['object']}")

        return tdl_dict

    def run_interactive(self):
        """대화형 모드 실행"""
        print("\n" + "=" * 80)
        print(" Interactive Mode - Master Pipeline")
        print("=" * 80)
        print("\nCommands:")
        print("  /help     - Show help")
        print("  /tsd      - Toggle TSD (Ground Truth State) on/off")
        print("  /dynamics - Toggle dynamics validation on/off")
        print("  /history  - Show execution history")
        print("  /quit     - Exit")
        print("\nOr enter natural language command:")
        print("=" * 80)

        enable_dynamics = True

        while True:
            try:
                user_input = input("\n> ").strip()

                if not user_input:
                    continue

                if user_input.lower() in ['/quit', '/exit', '/q']:
                    print("\nExiting. Goodbye!")
                    break

                elif user_input.lower() == '/help':
                    self._print_help()

                elif user_input.lower() == '/tsd':
                    self.use_tsd = not self.use_tsd
                    print(f"TSD (Ground Truth State): {'ON' if self.use_tsd else 'OFF'}")

                elif user_input.lower() == '/dynamics':
                    enable_dynamics = not enable_dynamics
                    print(f"Dynamics Validation: {'ON' if enable_dynamics else 'OFF'}")

                elif user_input.lower() == '/history':
                    self._print_history()

                else:
                    # 자연어 명령 실행
                    result = self.execute_full_pipeline(
                        user_nl=user_input,
                        enable_dynamics=enable_dynamics
                    )

                    print("\n" + "=" * 80)
                    if result['success']:
                        print(" [OK] PIPELINE SUCCESS!")
                        print("=" * 80)
                        print(f"\n  Message: {result['simulation'].get('message', 'Success')}")
                        print(f"  Plan: {result['simulation'].get('plan', 'N/A')}")
                        if 'video_path' in result['simulation']:
                            print(f"  Video: {result['simulation']['video_path']}")
                    else:
                        print(" [X] PIPELINE FAILED")
                        print("=" * 80)
                        print(f"\n  Error: {result.get('error', 'Unknown error')}")
                    print("=" * 80)

            except KeyboardInterrupt:
                print("\n\nInterrupted. Exiting...")
                break
            except Exception as e:
                print(f"\nError: {e}")
                logger.exception("Interactive mode error")

    def _print_help(self):
        """도움말 출력"""
        print("\n" + "-" * 80)
        print(" Help - Master Pipeline Commands")
        print("-" * 80)
        print("\nPipeline Steps:")
        print("  1. Ground Truth TSD (optional) - MuJoCo Observation → Text State")
        print("  2. NL → TDL v1 - Generate task description (with TSD context)")
        print("  3. Robot Selection - Choose best robot")
        print("  4. Dynamics Validation (optional) - Check physics feasibility")
        print("  5. Simulation - Execute in Roco and save video")
        print("\nExample Commands:")
        print('  "Pick the apple and place it in the bin"')
        print('  "Move the banana to the left side"')
        print('  "Inspect the milk container"')
        print("-" * 80)

    def _print_history(self):
        """실행 히스토리 출력"""
        if not self.history:
            print("\nNo execution history yet.")
            return

        print("\n" + "-" * 80)
        print(f" Execution History ({len(self.history)} items)")
        print("-" * 80)

        for i, item in enumerate(self.history, 1):
            status = "[OK]" if item['success'] else "[X]"
            print(f"\n{i}. {status} {item['user_nl']}")
            print(f"   Time: {item['timestamp']}")
            if item['success']:
                print(f"   Plan: {item['simulation'].get('plan', 'N/A')}")
                print(f"   Message: {item['simulation'].get('message', 'Success')}")
            else:
                print(f"   Error: {item.get('error', 'Unknown')}")

        print("-" * 80)


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='NL2TDL Master Pipeline')
    parser.add_argument('--tsd', action='store_true', default=True, help='Enable Ground Truth TSD generation (default: True)')
    parser.add_argument('--no-tsd', action='store_true', help='Disable Ground Truth TSD generation')
    parser.add_argument('--command', type=str, help='Execute single command')
    parser.add_argument('--no-dynamics', action='store_true', help='Disable dynamics validation')

    args = parser.parse_args()

    try:
        # TSD 플래그 결정 (--no-tsd가 있으면 False, 없으면 True)
        use_tsd = not args.no_tsd

        # 파이프라인 초기화
        pipeline = MasterPipeline(use_tsd=use_tsd)

        if args.command:
            # 단일 명령 실행
            result = pipeline.execute_full_pipeline(
                user_nl=args.command,
                enable_dynamics=not args.no_dynamics
            )

            if result['success']:
                print(f"\n[OK] SUCCESS")
                print(f"Plan: {result['simulation'].get('plan', 'N/A')}")
                print(f"Message: {result['simulation'].get('message', 'Success')}")
                if 'video_path' in result['simulation']:
                    print(f"Video: {result['simulation']['video_path']}")
                sys.exit(0)
            else:
                print(f"\n[X] FAILED: {result.get('error')}")
                sys.exit(1)
        else:
            # 대화형 모드
            pipeline.run_interactive()

    except KeyboardInterrupt:
        print("\n\nInterrupted by user. Exiting...")
        sys.exit(0)
    except Exception as e:
        print(f"\n\nFatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
