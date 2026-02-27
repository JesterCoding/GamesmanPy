from models import Game, Value, StringMode
from typing import Optional
from .chunk import SokobanWorld, SokobanChunk


class Sokoban(Game):
    id = 'sokoban'

    # No leading indentation — load_level_string is whitespace-sensitive
    custom_level = (
        "######\n"
        "###  #\n"
        "##.$ #\n"
        "#    #\n"
        "#@   #\n"
        "######"
    )

    another_level = (
        "#######"
        "##  ###"
        "##  ###"
        "##  ###"
        "### ###"
        "#  $  #"
        "# @ . #"
        "#######"
    )

    first_level = (
        "  ##### "
        "###   # " 
        "#.@$  # "
        "### $.# "
        "#.##$ # "
        "# # . # "
        "#$ $$$.#"
        "#   .  #"
        "########"
    )

    variants = ["Level 1", "Level 2", "Level 3", "Level 3.1", "Level 3.2", "Level 4"]
    n_players = 1
    cyclic = True

    # Tile ID constants (mirrors SokobanWorld palette)
    FLOOR  = 0
    WALL   = 1
    CRATE  = 2
    GOAL   = 3
    PLAYER = 4

    def __init__(self, variant_id: str):
        if variant_id not in Sokoban.variants:
            raise ValueError(f"Variant not defined: {variant_id!r}")
        
        match variant_id:
            case "Level 1":
                variant_id = (
                    "######\n"
                    "###  #\n"
                    "##.$ #\n"
                    "#    #\n"
                    "#@   #\n"
                    "######\n"
                )
            case "Level 2":
                variant_id = (
                    "#######\n"
                    "##  ###\n"
                    "##  ###\n"
                    "##  ###\n"
                    "### ###\n"
                    "#  $  #\n"
                    "# @ . #\n"
                    "#######\n"
                )
            case "Level 3":
                variant_id = (
                        "  ##### \n"
                        "###   # \n" 
                        "#.@$  # \n"
                        "### $.# \n"
                        "#.##$ # \n"
                        "# # . # \n"
                        "#$ *$$.#\n"
                        "#   .  #\n"
                        "########\n"
                )
            case "Level 3.1":
                    variant_id = (
                    "##########\n"
                    "#        #\n"
                    "# $$ $   #\n"
                    "#      ###\n"
                    "####   #  \n"
                    "   # @ #  \n"
                    "   # $ #  \n"
                    "####   ####\n"
                    "#....     #\n"
                    "###########\n"
                )
            case "Level 3.2":
                variant_id = (
                    "  #####  \n"
                    "  #   #  \n"
                    "###$  #  \n"
                    "#   $ #  \n"
                    "#   @ ###\n"
                    "##### $ #\n"
                    "  ### $ #\n"
                    "  #.... #\n"
                    "  #######\n"
                )
            #"                      \n"
            case "Level 4":
                variant_id = (
                    "    #####              \n"
                    "    #   #              \n"
                    "    #$  #              \n"
                    "  ###  $###            \n"
                    "  #  $  $ #            \n"
                    "### # ### #            \n"
                    "#   # ### #      ######\n"
                    "#   # ### ########  ..#\n"
                    "# $  $              ..#\n"
                    "##### ####  #@####  ..#\n"
                    "    #       ###  ######\n"
                    "    #########          \n"
                )

        self._variant_id = variant_id

        lines = [l for l in variant_id.strip().split('\n') if not l.startswith(';')]
        self.height = len(lines)
        self.width  = max(len(l) for l in lines)

        # Load the world once to extract static structure
        self.world = SokobanWorld(hash(variant_id), self.width, self.height)
        self.world.load_level_string(variant_id)

        # --- Static structure: walls and goals never change ---
        walls = set()
        for y in range(self.height):
            for x in range(self.width):
                if self.world.get_tile(x, y) == Sokoban.WALL:
                    walls.add((x, y))

        self.walls = frozenset(walls)
        self.goals = frozenset(self.world.goal_positions)

        # direction_id -> (dx, dy) — Up, Down, Left, Right
        self.directions = {0: (0, -1), 1: (0, 1), 2: (-1, 0), 3: (1, 0)}

        # -------------------------------------------------------
        # Direct bijective integer encoding
        #
        # free_cells: all non-wall cells in stable row-major order.
        # N = len(free_cells).
        #
        # A position integer is laid out as two packed fields:
        #
        #   position = (player_idx << N) | crate_bitmask
        #
        #   player_idx   — index of the player's cell in free_cells (0..len-1)
        #   crate_bitmask — bit i is 1 iff free_cells[i] holds a crate
        #
        # Because the encoding is computed solely from board content,
        # the same board state ALWAYS produces the same integer regardless
        # of how it was reached. The solver's remoteness values are therefore
        # stable and correct.
        # 
        # Before, the state would change every time a box would be pushed.
        # This caused different ways to reach and push a box in the state
        # to have the same value, causing overlap and mutation of states 
        # -------------------------------------------------------

        self.free_cells: list[tuple[int, int]] = [
            (x, y)
            for y in range(self.height)
            for x in range(self.width)
            if (x, y) not in self.walls
        ]
        self.N = len(self.free_cells)
        self.cell_to_idx: dict[tuple[int, int], int] = {
            cell: i for i, cell in enumerate(self.free_cells)
        }

    # ------------------------------------------------------------------
    # Encoding / decoding
    # ------------------------------------------------------------------
    def _encode(self, player: tuple[int, int], crates: frozenset) -> int:
        """Pack (player_pos, crate_set) into a single integer."""
        player_idx  = self.cell_to_idx[player]
        crate_mask  = 0
        for cell in crates:
            crate_mask |= 1 << self.cell_to_idx[cell]
        return (player_idx << self.N) | crate_mask

    def _decode(self, position: int) -> tuple[tuple[int, int], frozenset]:
        """Unpack a position integer into (player_pos, frozenset_of_crate_positions)."""
        crate_mask = position & ((1 << self.N) - 1)
        player_idx = position >> self.N
        player = self.free_cells[player_idx]
        crates = frozenset(
            self.free_cells[i]
            for i in range(self.N)
            if crate_mask & (1 << i)
        )
        return player, crates

    def _is_wall(self, x: int, y: int) -> bool:
        return not (0 <= x < self.width and 0 <= y < self.height) or (x, y) in self.walls

    # ------------------------------------------------------------------
    # GamesmanPy interface
    # ------------------------------------------------------------------

    def start(self) -> int:
        """Return the starting position as an integer."""
        px, py = self.world.player_pos
        crates = frozenset(
            (x, y)
            for y in range(self.height)
            for x in range(self.width)
            if self.world.get_tile(x, y) == Sokoban.CRATE
        )
        return self._encode((px, py), crates)

    def generate_moves(self, position: int) -> list[int]:
        """Return list of valid move integers from the given position."""
        player, crates = self._decode(position)
        px, py = player
        valid = []

        for move_id, (dx, dy) in self.directions.items():
            tx, ty = px + dx, py + dy

            if self._is_wall(tx, ty):
                continue

            if (tx, ty) in crates:
                bx, by = tx + dx, ty + dy
                if self._is_wall(bx, by) or (bx, by) in crates:
                    continue

            valid.append(move_id)

        return valid

    def do_move(self, position: int, move: int) -> int:
        """Apply move to position and return the resulting position as an integer."""
        player, crates = self._decode(position)
        px, py = player
        dx, dy = self.directions[move]
        tx, ty = px + dx, py + dy

        new_crates = crates
        if (tx, ty) in crates:
            bx, by = tx + dx, ty + dy
            new_crates = (crates - {(tx, ty)}) | {(bx, by)}

        return self._encode((tx, ty), new_crates)

    def primitive(self, position: int) -> Optional[Value]:
        """
        Win  — every goal cell contains a crate.
        Loss — no moves available (crates are deadlocked, not all on goals).
        None — game still in progress.
        """
        player, crates = self._decode(position)

        if self.goals <= crates:
            return Value.Win

        if self.check_loss_condition(crates):
            return Value.Loss

        return None

    def to_string(self, position: int, mode: StringMode) -> str:
        """Render the board for the given position as a string."""
        player, crates = self._decode(position)

        lines = []
        for y in range(self.height):
            row = ''
            for x in range(self.width):
                coord    = (x, y)
                is_goal  = coord in self.goals
                is_wall  = coord in self.walls

                if is_wall:
                    row += '#'
                elif coord == player:
                    row += '+' if is_goal else '@'  # + = player on goal
                elif coord in crates:
                    row += '*' if is_goal else '$'  # * = crate on goal
                elif is_goal:
                    row += '.'
                else:
                    row += ' '
            lines.append(row)
        return '\n'.join(lines)

    def from_string(self, strposition: str) -> int:
        """Parse a StringMode.Readable board string and return the position integer."""
        player = None
        crates = set()

        for y, line in enumerate(strposition.split('\n')):
            for x, ch in enumerate(line):
                if ch in ('@', '+'):    # @ = player, + = player on goal
                    player = (x, y)
                elif ch in ('$', '*'):  # $ = crate, * = crate on goal
                    crates.add((x, y))

        if player is None:
            raise ValueError("No player character (@/+) found in position string.")

        return self._encode(player, frozenset(crates))

    def move_to_string(self, move: int, mode: StringMode) -> str:
        return {0: "w", 1: "s", 2: "a", 3: "d"}.get(move, "Unknown")
    
    def check_loss_condition(self, crates: frozenset) -> Value | None:
        """
        Checks if any box is permanently trapped in a corner (or worse).
        A true corner means the box is blocked on at least one vertical axis 
        AND at least one horizontal axis.
        """
        for cx, cy in crates:
            # CRITICAL: If the box is already on a goal, it is allowed to be parked in a corner!
            if (cx, cy) in self.goals:
                continue
                
            # Check all four adjacent squares for walls
            wall_up = (cx, cy - 1) in self.walls
            wall_down = (cx, cy + 1) in self.walls
            wall_left = (cx - 1, cy) in self.walls
            wall_right = (cx + 1, cy) in self.walls
            
            # Is it blocked from moving vertically?
            is_blocked_vertically = wall_up or wall_down
            
            # Is it blocked from moving horizontally?
            is_blocked_horizontally = wall_left or wall_right
            
            # If it is blocked in BOTH directions, it is stuck in a corner.
            # (Note: This also naturally catches 3-wall and 4-wall deadlocks!)
            if is_blocked_vertically and is_blocked_horizontally:
                return True

        # If all crates are safe (or safely on goals)
        return False