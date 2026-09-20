import random

def create_bingo_card():
    """Generates a standard 5x5 Bingo card with a FREE space in the center."""
    card = {
        'B': random.sample(range(1, 16), 5),
        'I': random.sample(range(16, 31), 5),
        'N': random.sample(range(31, 46), 5),
        'G': random.sample(range(46, 61), 5),
        'O': random.sample(range(61, 76), 5)
    }
    # Standard center FREE space
    card['N'][2] = "FREE"
    return card

def print_card(card):
    """Displays the current state of the Bingo card."""
    print("\n  B   I   N   G   O")
    print("-" * 23)
    for row in range(5):
        row_str = []
        for col in ['B', 'I', 'N', 'G', 'O']:
            val = card[col][row]
            row_str.append(f"{str(val):>4}")
        print("".join(row_str))
    print("-" * 23)

def mark_number(card, number):
    """Marks matched numbers on the card with an 'X'."""
    for col in card:
        for i in range(5):
            if card[col][i] == number:
                card[col][i] = " X  "
                return True
    return False

def check_win(card):
    """Checks for completed rows, columns, or diagonals."""
    grid = [[card[col][row] for col in ['B', 'I', 'N', 'G', 'O']] for row in range(5)]
    
    # Helper to check if 5 items in a line are marked or FREE
    def is_line_marked(line):
        return all(str(val).strip() in ["X", "FREE"] for val in line)

    # Check rows and columns
    for i in range(5):
        if is_line_marked(grid[i]):  # Horizontal
            return True
        if is_line_marked([grid[row][i] for row in range(5)]):  # Vertical
            return True

    # Check diagonals
    diag1 = [grid[i][i] for i in range(5)]
    diag2 = [grid[i][4 - i] for i in range(5)]
    
    return is_line_marked(diag1) or is_line_marked(diag2)

def play_bingo():
    card = create_bingo_card()
    drawn_numbers = set()
    all_balls = list(range(1, 76))
    random.shuffle(all_balls)
    
    print("=== SIMPLE BINGO GAME ===")
    print_card(card)

    while all_balls:
        input("\nPress ENTER to draw the next ball...")
        drawn = all_balls.pop()
        drawn_numbers.add(drawn)
        
        print(f"--> Ball Drawn: {drawn}")
        hit = mark_number(card, drawn)
        if hit:
            print("MATCH FOUND!")
        
        print_card(card)
        
        if check_win(card):
            print("\n BINGO! YOU WIN! ")
            break

if __name__ == "__main__":
    play_bingo()
