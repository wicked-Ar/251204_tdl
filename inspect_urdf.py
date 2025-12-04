"""
URDF 파일 검사 도구
새로운 로봇 URDF를 추가할 때 필요한 정보를 자동으로 추출합니다.
"""
import pybullet as p
import pybullet_data
import sys

def inspect_urdf(urdf_path, base_position=[0, 0, 0], base_orientation=[0, 0, 0]):
    """
    URDF 파일을 로드하고 robot_db.json에 필요한 정보를 출력

    Args:
        urdf_path: URDF 파일 경로 (예: "doosan_h2515/h2515.urdf")
        base_position: 로봇 베이스 위치
        base_orientation: 로봇 베이스 방향 (Euler angles)
    """
    print("=" * 80)
    print(f"URDF Inspector - Analyzing: {urdf_path}")
    print("=" * 80)

    # PyBullet 연결 (GUI 모드)
    client = p.connect(p.GUI)
    p.setAdditionalSearchPath(pybullet_data.getDataPath())

    try:
        # URDF 로드
        print(f"\n[1/5] Loading URDF...")
        base_orn = p.getQuaternionFromEuler(base_orientation)
        robot_id = p.loadURDF(
            urdf_path,
            basePosition=base_position,
            baseOrientation=base_orn,
            useFixedBase=True
        )
        print(f"  ✓ URDF loaded successfully (ID: {robot_id})")

        # 조인트 정보 수집
        print(f"\n[2/5] Analyzing joints...")
        num_joints = p.getNumJoints(robot_id)
        print(f"  Total joints: {num_joints}")

        revolute_joints = []
        prismatic_joints = []
        fixed_joints = []

        print(f"\n  Joint Details:")
        print(f"  {'Index':<8} {'Name':<30} {'Type':<15} {'Lower':<10} {'Upper':<10}")
        print(f"  {'-'*80}")

        for i in range(num_joints):
            joint_info = p.getJointInfo(robot_id, i)
            joint_name = joint_info[1].decode('utf-8')
            joint_type = joint_info[2]
            joint_lower = joint_info[8]
            joint_upper = joint_info[9]

            type_name = {
                p.JOINT_REVOLUTE: "REVOLUTE",
                p.JOINT_PRISMATIC: "PRISMATIC",
                p.JOINT_FIXED: "FIXED",
                p.JOINT_SPHERICAL: "SPHERICAL",
                p.JOINT_PLANAR: "PLANAR"
            }.get(joint_type, f"UNKNOWN({joint_type})")

            print(f"  {i:<8} {joint_name:<30} {type_name:<15} {joint_lower:<10.3f} {joint_upper:<10.3f}")

            if joint_type == p.JOINT_REVOLUTE:
                revolute_joints.append(i)
            elif joint_type == p.JOINT_PRISMATIC:
                prismatic_joints.append(i)
            elif joint_type == p.JOINT_FIXED:
                fixed_joints.append(i)

        # 링크 정보
        print(f"\n[3/5] Finding end-effector link...")
        print(f"  Possible end-effector candidates:")

        for i in range(num_joints):
            joint_info = p.getJointInfo(robot_id, i)
            link_name = joint_info[12].decode('utf-8')

            # End-effector 후보 (일반적으로 "ee", "tool", "tcp", "flange" 등의 이름 포함)
            if any(keyword in link_name.lower() for keyword in ['ee', 'tool', 'tcp', 'flange', 'tip']):
                print(f"    Link {i}: {link_name} ← Likely end-effector")

        # 마지막 링크도 후보
        if num_joints > 0:
            last_joint_info = p.getJointInfo(robot_id, num_joints - 1)
            last_link_name = last_joint_info[12].decode('utf-8')
            print(f"    Link {num_joints - 1}: {last_link_name} ← Last link")

        # 그리퍼 조인트 찾기
        print(f"\n[4/5] Finding gripper joints...")
        gripper_candidates = []
        for i in range(num_joints):
            joint_info = p.getJointInfo(robot_id, i)
            joint_name = joint_info[1].decode('utf-8')

            # 그리퍼 후보 (일반적으로 "finger", "gripper" 등의 이름 포함)
            if any(keyword in joint_name.lower() for keyword in ['finger', 'gripper', 'hand']):
                gripper_candidates.append(i)
                print(f"    Joint {i}: {joint_name} ← Gripper joint")

        if not gripper_candidates:
            print(f"    No gripper joints found (gripper_joints: [])")

        # JSON 설정 생성
        print(f"\n[5/5] Generated pybullet_config:")
        print(f"  " + "=" * 76)

        # 기본 홈 포즈 계산 (중간값)
        controllable_joints = revolute_joints + prismatic_joints
        home_pose = []
        lower_limits = []
        upper_limits = []
        ranges = []

        for joint_idx in controllable_joints:
            joint_info = p.getJointInfo(robot_id, joint_idx)
            lower = joint_info[8]
            upper = joint_info[9]

            # 중간값으로 홈 포즈 설정
            home_val = (lower + upper) / 2.0
            home_pose.append(round(home_val, 4))
            lower_limits.append(round(lower, 4))
            upper_limits.append(round(upper, 4))
            ranges.append(round(upper - lower, 4))

        # 그리퍼 조인트도 홈 포즈에 포함 (열린 상태로)
        for joint_idx in gripper_candidates:
            joint_info = p.getJointInfo(robot_id, joint_idx)
            upper = joint_info[9]  # 열린 상태 = upper limit
            home_pose.append(round(upper, 4))

        config = f'''  "pybullet_config": {{
    "urdf_available": true,
    "urdf_path": "{urdf_path}",
    "base_position": {base_position},
    "base_orientation": {base_orientation},
    "home_pose": {home_pose},
    "ee_link_index": {num_joints - 1},  // ← 확인 필요! 위의 후보 중 선택
    "controllable_joints": {len(controllable_joints)},
    "gripper_joints": {gripper_candidates},
    "joint_limits": {{
      "lower": {lower_limits},
      "upper": {upper_limits},
      "ranges": {ranges},
      "rest_poses": {home_pose[:len(controllable_joints)]}
    }}
  }}'''

        print(config)
        print(f"  " + "=" * 76)

        print(f"\n[Summary]")
        print(f"  Controllable joints: {len(controllable_joints)} ({controllable_joints})")
        print(f"  Gripper joints: {len(gripper_candidates)} ({gripper_candidates})")
        print(f"  Suggested EE link: {num_joints - 1} (VERIFY THIS!)")

        print(f"\n[Next Steps]")
        print(f"  1. 위의 JSON을 robot_db.json의 해당 로봇에 복사")
        print(f"  2. ee_link_index 값을 실제 end-effector 링크 번호로 수정")
        print(f"  3. home_pose 값을 원하는 초기 자세로 조정")
        print(f"  4. base_position/orientation을 시뮬레이션 환경에 맞게 조정")

        print(f"\n[Keep window open to inspect robot visually...]")
        print(f"  Press Ctrl+C to exit")

        # GUI 창 유지
        while True:
            p.stepSimulation()
            import time
            time.sleep(1./240.)

    except Exception as e:
        print(f"\n[ERROR] Failed to load URDF: {e}")
        import traceback
        traceback.print_exc()

    finally:
        p.disconnect()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python inspect_urdf.py <urdf_path> [base_x base_y base_z] [roll pitch yaw]")
        print("")
        print("Examples:")
        print("  python inspect_urdf.py doosan_h2515/h2515.urdf")
        print("  python inspect_urdf.py doosan_h2515/h2515.urdf -0.6 0 0.625 0 0 0")
        print("  python inspect_urdf.py abb_irb1200/irb1200.urdf 0.6 0 0.625 0 0 3.14159")
        sys.exit(1)

    urdf_path = sys.argv[1]

    # 선택적 베이스 위치/방향
    if len(sys.argv) >= 5:
        base_pos = [float(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4])]
    else:
        base_pos = [0, 0, 0]

    if len(sys.argv) >= 8:
        base_ori = [float(sys.argv[5]), float(sys.argv[6]), float(sys.argv[7])]
    else:
        base_ori = [0, 0, 0]

    inspect_urdf(urdf_path, base_pos, base_ori)
