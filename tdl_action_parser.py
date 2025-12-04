"""
TDL Action Parser
=================
Parses TDL (Task Description Language) files to extract sequential action sequences.

This parser analyzes the Execute_Process() GOAL block to identify pick and place
operations based on:
- SetWorkpieceWeight() commands → object identification
- SetDigitalOutput(0, 1) → gripper close → pick action
- SetDigitalOutput(0, 0) → gripper open → place action (after pick)

Author: AYN System
Date: 2025-12-02
"""

import re
from typing import List, Dict, Optional


class TDLActionParser:
    """
    Parses TDL content to extract sequential pick/place actions.

    Attributes:
        weight_to_object (dict): Mapping from object weight (kg) to object name
        gripper_state (str): Tracks gripper state during parsing ('open' or 'closed')
        current_object (str): Tracks currently targeted object
    """

    def __init__(self):
        """
        Initialize the TDL parser with weight-to-object mappings.

        Standard object weights:
        - Apple: 0.2 kg
        - Banana: 0.12 kg
        - Orange: 0.5 kg
        """
        self.weight_to_object = {
            0.2: 'apple',
            0.12: 'banana',
            0.5: 'orange',
            0.15: 'cup',
            0.3: 'bottle'
        }

    def parse_tdl_to_actions(self, tdl_content: str) -> List[Dict]:
        """
        Parse TDL content to extract action sequence.

        Args:
            tdl_content (str): Complete TDL file content

        Returns:
            List[Dict]: List of action dictionaries with format:
                [
                    {'action': 'pick', 'object': 'apple', 'weight': 0.2},
                    {'action': 'place', 'object': 'apple', 'weight': 0.2},
                    {'action': 'pick', 'object': 'banana', 'weight': 0.12},
                    ...
                ]

        Algorithm:
            1. Extract Execute_Process() GOAL block
            2. Track gripper state (open/closed)
            3. Identify workpiece weights → infer object names
            4. Detect pick actions (gripper close after open)
            5. Detect place actions (gripper open after close)
        """
        actions = []
        gripper_state = 'open'  # Initial state: gripper open
        current_object = None
        current_weight = None

        # First, scan entire TDL to find first workpiece weight (usually in Initialize_Process)
        all_lines = tdl_content.split('\n')
        for line in all_lines:
            if 'SetWorkpieceWeight' in line:
                weight = self._extract_weight(line)
                if weight is not None:
                    current_weight = weight
                    current_object = self._extract_object_from_weight(weight)
                    print(f"[TDL Parser] Initial object found: {current_object} (weight: {weight} kg)")
                    break  # Use first weight as default

        # Extract Execute_Process() block for action parsing
        execute_block = self._extract_execute_process_block(tdl_content)
        if not execute_block:
            print("[TDL Parser] Warning: No Execute_Process() block found")
            return actions

        # Parse line by line
        lines = execute_block.split('\n')
        for line in lines:
            line = line.strip()

            # Detect SetWorkpieceWeight() → update object
            if 'SetWorkpieceWeight' in line:
                weight = self._extract_weight(line)
                if weight is not None:
                    current_weight = weight
                    current_object = self._extract_object_from_weight(weight)
                    print(f"[TDL Parser] Object updated: {current_object} (weight: {weight} kg)")

            # Detect SetDigitalOutput(*, 1) → gripper close → pick action
            if 'SetDigitalOutput' in line and ', 1)' in line:
                if gripper_state == 'open' and current_object:
                    actions.append({
                        'action': 'pick',
                        'object': current_object,
                        'weight': current_weight
                    })
                    gripper_state = 'closed'
                    print(f"[TDL Parser] Action #{len(actions)}: pick {current_object}")

            # Detect SetDigitalOutput(*, 0) → gripper open → place action (if after pick)
            if 'SetDigitalOutput' in line and ', 0)' in line:
                if gripper_state == 'closed' and current_object:
                    actions.append({
                        'action': 'place',
                        'object': current_object,
                        'weight': current_weight
                    })
                    gripper_state = 'open'
                    print(f"[TDL Parser] Action #{len(actions)}: place {current_object}")

        print(f"[TDL Parser] Total actions extracted: {len(actions)}")
        return actions

    def _extract_execute_process_block(self, tdl_content: str) -> Optional[str]:
        """
        Extract the Execute_Process() GOAL block from TDL content.

        Args:
            tdl_content (str): Complete TDL file content

        Returns:
            str: Content inside Execute_Process() block, or None if not found
        """
        # Find GOAL Execute_Process() { ... }
        pattern = r'GOAL\s+Execute_Process\s*\(\s*\)\s*\{(.*?)\n\}'
        match = re.search(pattern, tdl_content, re.DOTALL)

        if match:
            return match.group(1)
        else:
            return None

    def _extract_weight(self, line: str) -> Optional[float]:
        """
        Extract weight value from SetWorkpieceWeight() command.

        Args:
            line (str): TDL line containing SetWorkpieceWeight command

        Returns:
            float: Weight in kg, or None if parsing fails

        Example:
            Input: "SPAWN SetWorkpieceWeight(0.2, Trans(0, 0, 80, 0, 0, 0)) WITH WAIT;"
            Output: 0.2
        """
        # Pattern: SetWorkpieceWeight(0.2, ...)
        pattern = r'SetWorkpieceWeight\s*\(\s*([\d.]+)'
        match = re.search(pattern, line)

        if match:
            try:
                weight = float(match.group(1))
                return weight
            except ValueError:
                return None
        return None

    def _extract_object_from_weight(self, weight: float) -> str:
        """
        Map object weight to object name using predefined dictionary.

        Args:
            weight (float): Object weight in kg

        Returns:
            str: Object name (e.g., 'apple', 'banana'), or 'unknown_object' if not found
        """
        # Exact match
        if weight in self.weight_to_object:
            return self.weight_to_object[weight]

        # Fuzzy match (±0.01 kg tolerance for floating point errors)
        for known_weight, obj_name in self.weight_to_object.items():
            if abs(weight - known_weight) < 0.01:
                return obj_name

        # Unknown object
        print(f"[TDL Parser] Warning: Unknown object weight {weight} kg")
        return f'unknown_object_{weight}kg'

    def add_object_weight_mapping(self, weight: float, object_name: str):
        """
        Add a new object weight mapping dynamically.

        Args:
            weight (float): Object weight in kg
            object_name (str): Object name (e.g., 'strawberry')
        """
        self.weight_to_object[weight] = object_name
        print(f"[TDL Parser] Added mapping: {weight} kg → {object_name}")


# Unit test
if __name__ == "__main__":
    # Test with sample TDL content
    sample_tdl = """
GOAL Execute_Process()
{
    // Apple Pick and Place
    SPAWN SetWorkpieceWeight(0.2, Trans(0, 0, 80, 0, 0, 0)) WITH WAIT;
    SPAWN MoveJoint(apple_approach, 50, 50, 0, 0.0, None) WITH WAIT;
    SPAWN SetDigitalOutput(0, 1) WITH WAIT; // Close gripper - PICK
    SPAWN MoveJoint(place_approach, 50, 50, 0, 0.0, None) WITH WAIT;
    SPAWN SetDigitalOutput(0, 0) WITH WAIT; // Open gripper - PLACE

    // Banana Pick
    SPAWN SetWorkpieceWeight(0.12, Trans(0, 0, 80, 0, 0, 0)) WITH WAIT;
    SPAWN MoveJoint(banana_approach, 50, 50, 0, 0.0, None) WITH WAIT;
    SPAWN SetDigitalOutput(0, 1) WITH WAIT; // Close gripper - PICK
}
    """

    parser = TDLActionParser()
    actions = parser.parse_tdl_to_actions(sample_tdl)

    print("\n=== Test Results ===")
    for i, action in enumerate(actions, 1):
        print(f"Action {i}: {action['action']} {action['object']} (weight: {action['weight']} kg)")

    expected_actions = [
        {'action': 'pick', 'object': 'apple', 'weight': 0.2},
        {'action': 'place', 'object': 'apple', 'weight': 0.2},
        {'action': 'pick', 'object': 'banana', 'weight': 0.12}
    ]

    if actions == expected_actions:
        print("\n[OK] Test PASSED")
    else:
        print("\n[FAIL] Test FAILED")
        print(f"Expected: {expected_actions}")
        print(f"Got: {actions}")
