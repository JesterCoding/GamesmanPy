import random

# A constant to enforce the 64-bit limit (SQLite BIGINT max is 2^63 - 1)
MAX_64_BIT = 0xFFFFFFFFFFFFFFFF

class SokobanChunk:
    def __init__(self, x, y, base_seed):
        self.x = x
        self.y = y
        
        # 1. Coordinate Hashing
        # We mix the base seed with the X and Y coordinates using bitwise XOR (^).
        # We shift X and Y so they don't overlap in the binary sequence.
        combined_hash = base_seed ^ ((x & 0xFFFFFFFF) << 32) ^ (y & 0xFFFFFFFF)
        self.chunk_seed = combined_hash & MAX_64_BIT
        
        # 2. Bit Unpacking
        # Slicing the 64-bit chunk_seed into distinct traits
        self.theme_id = self.chunk_seed & 0xFFFF                  # First 16 bits (0-65535)
        self.density  = (self.chunk_seed >> 16) & 0xFFFF          # Next 16 bits (0-65535)
        self.entropy  = (self.chunk_seed >> 32) & 0xFFFFFFFF      # Last 32 bits for layout math
        
        # The actual level data (Palette-based: 0=Floor, 1=Wall, 2=Crate)
        self.grid = []
        self.generate_layout()

    def generate_layout(self):
        """Deterministically generates the 16x16 grid using the chunk's entropy."""
        # We use the entropy as the seed for our PRNG so it's always the same for this chunk
        random.seed(self.entropy)
        
        # Normalize density to a percentage (0.0 to 1.0)
        wall_chance = (self.density / 65535.0) * 0.3 # Max 30% walls so it remains playable
        
        for row in range(16):
            grid_row = []
            for col in range(16):
                # Simple generation logic
                if random.random() < wall_chance:
                    grid_row.append(1) # 1 = Wall
                else:
                    grid_row.append(0) # 0 = Floor
            self.grid.append(grid_row)
            
        # Guarantee at least one crate (2) per chunk for testing
        crate_x, crate_y = random.randint(0, 15), random.randint(0, 15)
        self.grid[crate_y][crate_x] = 2

    def display(self):
        """Helper to visualize the chunk."""
        symbols = {0: ".", 1: "#", 2: "C"}
        print(f"--- Chunk ({self.x}, {self.y}) | Theme: {self.theme_id} | Walls: {self.density/65535:.0%} ---")
        for row in self.grid:
            print(" ".join(symbols[tile] for tile in row))
        print("\n")


class SokobanWorld:
    def __init__(self, seed, width=None, height=None):
        self.seed = seed
        self.width = width
        self.height = height
        self.active_chunks = {}
        self.player_pos = [0, 0] # We'll track this for the game loop
        self.goal_positions = set()

    def get_tile(self, x, y):
        # Boundary Check
        if self.width and self.height:
            if x < 0 or x >= self.width or y < 0 or y >= self.height:
                return 1 # Wall
        
        chunk_x, local_x = divmod(x, 16)
        chunk_y, local_y = divmod(y, 16)
        key = (chunk_x, chunk_y)

        if key not in self.active_chunks:
            self.active_chunks[key] = SokobanChunk(chunk_x, chunk_y, self.seed)
        
        return self.active_chunks[key].grid[local_y][local_x]

    def set_tile(self, x, y, tile_id):
        """Forces a specific tile into a chunk, creating the chunk if it doesn't exist."""
        chunk_x, local_x = divmod(x, 16)
        chunk_y, local_y = divmod(y, 16)
        key = (chunk_x, chunk_y)

        if key not in self.active_chunks:
            self.active_chunks[key] = SokobanChunk(chunk_x, chunk_y, self.seed)
        
        self.active_chunks[key].grid[local_y][local_x] = tile_id

        if tile_id == 3: 
            self.goal_positions.add((x, y))
        
        # If we just placed a player, update the player_pos tracker
        if tile_id == 4:
            self.player_pos = [x, y]

    def is_solved(self):
        """Checks if every goal coordinate contains a crate."""
        if not self.goal_positions:
            return False
            
        for (gx, gy) in self.goal_positions:
            if self.get_tile(gx, gy) != 2: # 2 is Crate
                return False
        return True

    def load_level_string(self, level_str, offset_x=0, offset_y=0):
        """The Stamping Function inside the World class."""
        palette = {' ': 0, '#': 1, '$': 2, '.': 3, '@': 4}
        lines = level_str.strip('\n').split('\n')
        
        for r, line in enumerate(lines):
            if line.startswith(';'): continue # Skip comments
            for c, char in enumerate(line):
                wx, wy = offset_x + c, offset_y + r

                if char == '*':
                    # Crate sitting on a goal square.
                    # Register the goal first (set_tile(GOAL) adds to goal_positions),
                    # then overwrite with CRATE so the grid value is 2, not 3.
                    self.set_tile(wx, wy, 3)  # mark as goal
                    self.set_tile(wx, wy, 2)  # place crate on top

                elif char == '+':
                    # Player standing on a goal square.
                    self.set_tile(wx, wy, 3)  # mark as goal
                    self.set_tile(wx, wy, 4)  # place player on top

                elif char in palette:
                    self.set_tile(wx, wy, palette[char])
        

    def move_player(self, dx, dy):
        """
        dx, dy: The direction of movement (e.g., [0, 1] for Down, [-1, 0] for Left)
        """
        curr_x, curr_y = self.player_pos
        target_x, target_y = curr_x + dx, curr_y + dy
        
        # 1. Get the tile at the target location
        target_tile = self.get_tile(target_x, target_y)
        
        # CASE A: Target is a Wall (#)
        if target_tile == 1:
            return False # Movement blocked
            
        # CASE B: Target is a Crate ($)
        if target_tile == 2:
            # Check the space behind the crate
            behind_x, behind_y = target_x + dx, target_y + dy
            behind_tile = self.get_tile(behind_x, behind_y)
            
            # Can we push the crate? (Only into Floor (0) or Goal (3))
            if behind_tile in [0, 3]:
                # Move the crate
                self.set_tile(behind_x, behind_y, 2)
                # Move the player into the crate's old spot
                self.set_tile(target_x, target_y, 4)
                # Leave the player's old spot empty (or a goal if it was one)
                # Note: Real Sokoban needs to track if a tile is a 'Goal' base.
                self.set_tile(curr_x, curr_y, 0) 
                self.player_pos = [target_x, target_y]
                return True
            else:
                return False # Crate is blocked by a wall or another crate
                
        # CASE C: Target is Floor (0) or Goal (3)
        if target_tile in [0, 3]:
            self.set_tile(target_x, target_y, 4)
            self.set_tile(curr_x, curr_y, 0)
            self.player_pos = [target_x, target_y]
            return True

        return False

def get_display_char(world, x, y):
        tile = world.get_tile(x, y)
        
        # If the tile is empty (0) but the coordinates are in our goal list
        if tile == 0 and (x, y) in world.goal_positions:
            return "." # Display as Goal
    
        return {0: " ", 1: "#", 2: "$", 3: ".", 4: "@"}[tile]

def play_game(world):
        controls = {'w': (0, -1), 's': (0, 1), 'a': (-1, 0), 'd': (1, 0)}
        
        while True:
            # 1. Clear and Draw
            print("\033[H\033[J", end="") 
            for y in range(world.height):
                line = "".join(get_display_char(world, x, y) for x in range(world.width))
                print(line)
                
            # 2. Check Win Condition
            if world.is_solved():
                print("\n Level Complete! You moved the crates to the goals! ")
                break

            # 3. Input
            move = input("\nMove (WASD) or 'q' to quit: ").lower()
            if move == 'q': break
            if move in controls:
                dx, dy = controls[move]
                world.move_player(dx, dy)

# --- Let's run it! ---
"""
custom_level = 
; Level 3
######
###  #
##.$ #
#    #
#@   #
######

# Try it out with your custom level!
world = SokobanWorld(seed=123, width=10, height=10)
world.load_level_string(custom_level)
play_game(world)


# A random 64-bit seed from your SQLite database
SQLITE_SEED = 8440932152345 
world = SokobanWorld(SQLITE_SEED)

# Notice we didn't generate a massive grid. We just ask for a chunk halfway across the continent.
print("Fetching a chunk far away...")
world.get_tile(16000, -8000) # This forces Chunk (1000, -500) to generate

# Let's display it
world.active_chunks[(1000, -500)].display()

# If we ask for the exact same chunk again, it doesn't recalculate. It just reads RAM.
world.active_chunks[(1000, -500)].display()
"""