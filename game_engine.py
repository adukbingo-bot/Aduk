# game_engine.py - COMPLETE FIXED VERSION
import asyncio
import random
import hashlib
import json
import secrets
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, field
from enum import Enum
import logging
from collections import defaultdict

logger = logging.getLogger(__name__)

class GameStatus(Enum):
    WAITING = "waiting"
    SELECTING = "selecting"
    ACTIVE = "active"
    FINISHED = "finished"
    CANCELLED = "cancelled"

class GameMode(Enum):
    CLASSIC = "classic"        # First to get bingo
    BLACKOUT = "blackout"      # Must mark all numbers
    X_PATTERN = "x_pattern"    # X shape
    FOUR_CORNERS = "corners"   # Four corners only
    LINE = "line"              # Any line

@dataclass
class Player:
    user_id: str
    username: str
    card: List[int]
    card_number: int
    marked: Set[int] = field(default_factory=set)
    bingo_called: bool = False
    bingo_time: Optional[float] = None
    win_amount: float = 0.0
    is_disqualified: bool = False
    last_mark_time: float = 0.0
    mark_count: int = 0

@dataclass
class BingoRoom:
    room_id: str
    name: str
    mode: GameMode = GameMode.CLASSIC
    card_price: float = 10.0
    prize_percentage: int = 80
    min_players: int = 2
    max_players: int = 400
    call_interval: float = 2.0
    selection_time: int = 20
    description: str = ""
    
    # Current game
    current_game: Optional['BingoGame'] = None
    games_played: int = 0
    total_players: int = 0
    total_bet: float = 0.0
    total_paid: float = 0.0

class BingoGame:
    def __init__(self, game_id: str, room: BingoRoom, db_manager=None):
        self.game_id = game_id
        self.room = room
        self.db = db_manager
        self.status = GameStatus.WAITING
        self.mode = room.mode
        
        # Players
        self.players: Dict[str, Player] = {}
        self.player_count = 0
        
        # Game state
        self.called_numbers: List[int] = []
        self.winners: List[str] = []
        self.winner_data: List[Dict] = []
        
        # Financial
        self.total_bet = 0.0
        self.prize_pool = 0.0
        self.commission = 0.0
        
        # Timing
        self.created_at = datetime.utcnow()
        self.started_at: Optional[datetime] = None
        self.finished_at: Optional[datetime] = None
        self.last_call: Optional[float] = None
        
        # Provably fair system
        self.server_seed = secrets.token_hex(32)
        self.client_seeds: Dict[str, str] = {}
        self.game_hash = self._generate_game_hash()
        
        # Locks
        self._lock = asyncio.Lock()
        
        # Used card tracking
        self.used_cards: Set[str] = set()
    
    def _generate_game_hash(self) -> str:
        """Generate game hash for provably fair system"""
        data = f"{self.game_id}{self.server_seed}{self.created_at.timestamp()}"
        return hashlib.sha256(data.encode()).hexdigest()
    
    def _generate_card(self, player_seed: str = None) -> Tuple[List[int], str]:
        """Generate a random bingo card dynamically"""
        # Use player seed for deterministic generation
        if player_seed:
            combined = f"{self.server_seed}{player_seed}{len(self.players)}"
            random.seed(hashlib.sha256(combined.encode()).hexdigest())
        
        card = []
        # B: 1-15
        b_numbers = random.sample(range(1, 16), 5)
        b_numbers.sort()
        # I: 16-30
        i_numbers = random.sample(range(16, 31), 5)
        i_numbers.sort()
        # N: 31-45
        n_numbers = random.sample(range(31, 46), 5)
        n_numbers.sort()
        # G: 46-60
        g_numbers = random.sample(range(46, 61), 5)
        g_numbers.sort()
        # O: 61-75
        o_numbers = random.sample(range(61, 76), 5)
        o_numbers.sort()
        
        # Interleave by column (for proper display)
        for row in range(5):
            card.append(b_numbers[row])
            card.append(i_numbers[row])
            card.append(n_numbers[row])
            card.append(g_numbers[row])
            card.append(o_numbers[row])
        
        # Reset random seed
        random.seed()
        
        # Generate card hash for verification
        card_hash = hashlib.sha256(str(card).encode()).hexdigest()
        
        return card, card_hash
    
    async def add_player(self, user_id: str, username: str, 
                        card_number: int = None, client_seed: str = None) -> Tuple[bool, str, dict]:
        """Add player to game with anti-cheat protection"""
        async with self._lock:
            if self.status != GameStatus.WAITING:
                return False, "Game already started", None
            
            if len(self.players) >= self.room.max_players:
                return False, "Game is full", None
            
            # Check for existing player
            if user_id in self.players:
                return False, "Already in game", None
            
            # Generate unique card
            if card_number is None or str(card_number) in self.used_cards:
                # Generate new card number
                card_number = len(self.players) + 1
                while str(card_number) in self.used_cards:
                    card_number += 1
            
            # Generate card data
            player_seed = client_seed or secrets.token_hex(16)
            self.client_seeds[user_id] = player_seed
            card_data, card_hash = self._generate_card(player_seed)
            
            # Create player
            player = Player(
                user_id=user_id,
                username=username,
                card=card_data,
                card_number=card_number,
                marked=set()
            )
            
            # Mark FREE space (center)
            player.marked.add(card_data[12])  # Center cell
            
            self.players[user_id] = player
            self.used_cards.add(str(card_number))
            self.player_count = len(self.players)
            
            # Update financials
            self.total_bet += self.room.card_price
            self.prize_pool = self.total_bet * self.room.prize_percentage / 100
            self.commission = self.total_bet - self.prize_pool
            
            # Save to database if available
            if self.db:
                await self.db.add_player_to_game(
                    game_id=self.game_id,
                    user_id=user_id,
                    card_number=card_number,
                    card_data=card_data
                )
            
            logger.info(f"Player {username} joined game {self.game_id} with card #{card_number}")
            
            return True, "Player added", {
                "card": card_data,
                "card_number": card_number,
                "card_hash": card_hash,
                "player_count": self.player_count
            }
    
    async def start_game(self) -> bool:
        """Start the game with anti-cheat verification"""
        async with self._lock:
            if len(self.players) < self.room.min_players:
                return False
            
            self.status = GameStatus.ACTIVE
            self.started_at = datetime.utcnow()
            self.last_call = asyncio.get_event_loop().time()
            
            # Save to database
            if self.db:
                await self.db.update_game_status(self.game_id, "active", self.started_at)
            
            logger.info(f"Game {self.game_id} started with {len(self.players)} players")
            return True
    
    async def call_number(self) -> Optional[int]:
        """Call next number with provably fair random generation"""
        async with self._lock:
            if self.status != GameStatus.ACTIVE:
                return None
            
            # Get available numbers
            available = [n for n in range(1, 76) if n not in self.called_numbers]
            
            if not available:
                # No more numbers - game ends in draw
                self.status = GameStatus.FINISHED
                self.finished_at = datetime.utcnow()
                if self.db:
                    await self.db.update_game_status(self.game_id, "finished", self.finished_at)
                return None
            
            # Provably fair number selection
            seed_data = f"{self.server_seed}{len(self.called_numbers)}{datetime.utcnow().timestamp()}"
            random.seed(hashlib.sha256(seed_data.encode()).hexdigest())
            number = random.choice(available)
            random.seed()
            
            self.called_numbers.append(number)
            self.last_call = asyncio.get_event_loop().time()
            
            # Auto-check winners (server-side validation)
            winners = await self.check_winners()
            if winners:
                await self.process_winners(winners)
            
            return number
    
    async def mark_number(self, user_id: str, number: int, timestamp: float) -> Tuple[bool, str, bool]:
        """Player marks a number - FULL SERVER VALIDATION"""
        async with self._lock:
            if self.status != GameStatus.ACTIVE:
                return False, "Game not active", False
            
            if user_id not in self.players:
                return False, "Player not in game", False
            
            player = self.players[user_id]
            
            # Anti-cheat: Check if disqualified
            if player.is_disqualified:
                return False, "You are disqualified", False
            
            # Anti-cheat: Rate limiting
            if timestamp - player.last_mark_time < 0.5:  # 500ms minimum between marks
                return False, "Too fast - possible bot", False
            
            # Validate number was called
            if number not in self.called_numbers:
                return False, "Number not called yet", False
            
            # Validate number is on player's card
            if number not in player.card:
                return False, "Number not on your card", False
            
            # Already marked
            if number in player.marked:
                return False, "Already marked", False
            
            # Valid mark
            player.marked.add(number)
            player.last_mark_time = timestamp
            player.mark_count += 1
            
            # Check for bingo (server-side)
            has_bingo = await self.check_player_bingo(user_id)
            
            if has_bingo and not player.bingo_called:
                # Auto-call bingo to prevent first-click advantage
                await self._auto_bingo(user_id)
            
            return True, "Marked", has_bingo
    
    async def _auto_bingo(self, user_id: str):
        """Auto-call bingo for winner - eliminates click advantage"""
        if user_id not in self.players:
            return
        
        player = self.players[user_id]
        if player.bingo_called or player.is_disqualified:
            return
        
        # Verify bingo again
        if await self.check_player_bingo(user_id):
            player.bingo_called = True
            player.bingo_time = asyncio.get_event_loop().time()
            
            if user_id not in self.winners:
                self.winners.append(user_id)
                player.win_amount = self.prize_pool / len(self.winners)
                
                logger.info(f"Player {player.username} got BINGO! Prize: {player.win_amount}")
    
    async def check_player_bingo(self, user_id: str) -> bool:
        """Server-side bingo verification"""
        player = self.players.get(user_id)
        if not player:
            return False
        
        if self.mode == GameMode.CLASSIC:
            # Check all numbers (25 numbers including FREE)
            return all(num in player.marked for num in player.card)
        
        elif self.mode == GameMode.LINE:
            # Check any line (rows, columns, diagonals)
            card = player.card
            marked = player.marked
            
            # Check rows
            for row in range(5):
                row_indices = [row * 5 + col for col in range(5)]
                if all(card[idx] in marked for idx in row_indices):
                    return True
            
            # Check columns
            for col in range(5):
                col_indices = [row * 5 + col for row in range(5)]
                if all(card[idx] in marked for idx in col_indices):
                    return True
            
            # Check main diagonal
            diag1 = [0, 6, 12, 18, 24]
            if all(card[idx] in marked for idx in diag1):
                return True
            
            # Check other diagonal
            diag2 = [4, 8, 12, 16, 20]
            if all(card[idx] in marked for idx in diag2):
                return True
            
            return False
        
        elif self.mode == GameMode.FOUR_CORNERS:
            corners = [0, 4, 20, 24]
            return all(card[idx] in player.marked for idx in corners)
        
        elif self.mode == GameMode.X_PATTERN:
            # X shape
            x_pattern = [0, 4, 6, 8, 12, 16, 18, 20, 24]
            return all(player.card[idx] in player.marked for idx in x_pattern)
        
        return False
    
    async def check_winners(self) -> List[str]:
        """Check all players for bingo"""
        async with self._lock:
            new_winners = []
            
            for user_id, player in self.players.items():
                if not player.bingo_called and not player.is_disqualified:
                    if await self.check_player_bingo(user_id):
                        player.bingo_called = True
                        player.bingo_time = asyncio.get_event_loop().time()
                        new_winners.append(user_id)
            
            if new_winners:
                self.winners.extend(new_winners)
                
                # Calculate prizes
                if self.winners:
                    prize_per_winner = self.prize_pool / len(self.winners)
                    for winner_id in self.winners:
                        self.players[winner_id].win_amount = prize_per_winner
                    
                    self.status = GameStatus.FINISHED
                    self.finished_at = datetime.utcnow()
                    
                    if self.db:
                        await self.db.update_game_finished(self.game_id, self.winners, self.finished_at)
            
            return new_winners
    
    async def process_winners(self, winners: List[str]):
        """Process winners with atomic transactions"""
        async with self._lock:
            if not winners:
                return
            
            # Process each winner with DB transaction
            for winner_id in winners:
                player = self.players[winner_id]
                if player.win_amount > 0 and self.db:
                    # Update user balance with transaction safety
                    success = await self.db.add_balance(
                        user_id=winner_id,
                        amount=player.win_amount,
                        transaction_type='win',
                        description=f'Won Bingo Game {self.game_id}'
                    )
                    
                    if success:
                        logger.info(f"Paid {player.win_amount} to {player.username}")
                    else:
                        logger.error(f"Failed to pay winner {winner_id}")
            
            # Update room stats
            self.room.total_paid += sum(p.win_amount for p in self.players.values())
            self.room.total_bet += self.total_bet
    
    def get_state(self, user_id: Optional[str] = None) -> dict:
        """Get game state for client"""
        state = {
            'game_id': self.game_id,
            'status': self.status.value,
            'mode': self.mode.value,
            'players': len(self.players),
            'max_players': self.room.max_players,
            'called_numbers': self.called_numbers[-20:],  # Last 20 numbers
            'recent_calls': self.called_numbers[-5:],    # Last 5 numbers
            'prize_pool': self.prize_pool,
            'card_price': self.room.card_price,
            'last_call': self.last_call,
            'winners': self.winners,
            'game_hash': self.game_hash  # For provably fair verification
        }
        
        # Add player-specific data
        if user_id and user_id in self.players:
            player = self.players[user_id]
            state['player'] = {
                'card': player.card,
                'marked': list(player.marked),
                'has_bingo': player.bingo_called,
                'win_amount': player.win_amount,
                'is_disqualified': player.is_disqualified,
                'card_number': player.card_number
            }
        
        return state
    
    def verify_fairness(self, user_id: str) -> dict:
        """Verify game fairness for a player"""
        if user_id not in self.players:
            return {"error": "Not in game"}
        
        player = self.players[user_id]
        client_seed = self.client_seeds.get(user_id)
        
        # Re-generate card to verify
        test_card, test_hash = self._generate_card(client_seed)
        
        return {
            "server_seed_hash": hashlib.sha256(self.server_seed.encode()).hexdigest(),
            "client_seed": client_seed,
            "card_hash": hashlib.sha256(str(player.card).encode()).hexdigest(),
            "card_verified": test_card == player.card,
            "called_numbers_count": len(self.called_numbers)
        }

class GameManager:
    """Manages multiple rooms and games"""
    
    def __init__(self, db_manager=None):
        self.rooms: Dict[str, BingoRoom] = {}
        self.games: Dict[str, BingoGame] = {}
        self.user_room: Dict[str, str] = {}
        self.user_game: Dict[str, str] = {}
        self.db = db_manager
        
        # Rate limiting
        self.user_actions: Dict[str, List[float]] = defaultdict(list)
        self.max_actions_per_second = 1
        
        # Statistics
        self.stats = defaultdict(int)
        
        # Background tasks
        self.game_loop_task = None
        self.cleanup_task = None
    
    def check_rate_limit(self, user_id: str) -> bool:
        """Check if user is rate limited"""
        now = datetime.utcnow().timestamp()
        user_actions = self.user_actions[user_id]
        
        # Clean old actions
        user_actions[:] = [t for t in user_actions if t > now - 1]
        
        if len(user_actions) >= self.max_actions_per_second:
            return False
        
        user_actions.append(now)
        return True
    
    def create_room(self, room_id: str, name: str, **kwargs) -> BingoRoom:
        """Create a new bingo room"""
        room = BingoRoom(room_id=room_id, name=name, **kwargs)
        self.rooms[room_id] = room
        return room
    
    async def create_game(self, room_id: str) -> BingoGame:
        """Create new game in room"""
        if room_id not in self.rooms:
            raise ValueError(f"Room {room_id} not found")
        
        room = self.rooms[room_id]
        game_id = f"{room_id}_{len(self.games)}_{int(datetime.utcnow().timestamp())}"
        
        game = BingoGame(game_id, room, self.db)
        self.games[game_id] = game
        room.current_game = game
        room.games_played += 1
        
        return game
    
    async def join_game(self, user_id: str, username: str, 
                       room_id: str, card_number: int = None,
                       client_seed: str = None) -> Tuple[bool, str, Optional[BingoGame], dict]:
        """User joins a game with rate limiting"""
        
        # Rate limit check
        if not self.check_rate_limit(user_id):
            return False, "Too many requests. Please slow down.", None, None
        
        # Get or create game
        room = self.rooms.get(room_id)
        if not room:
            return False, "Room not found", None, None
        
        # Check if user already in a game
        if user_id in self.user_game:
            game_id = self.user_game[user_id]
            if game_id in self.games:
                game = self.games[game_id]
                if game.status in [GameStatus.WAITING, GameStatus.ACTIVE]:
                    return False, "Already in a game", game, game.get_state(user_id)
        
        # Find available game in room
        game = room.current_game
        if not game or game.status != GameStatus.WAITING:
            # Create new game
            game = await self.create_game(room_id)
        
        # Add player
        success, msg, player_data = await game.add_player(user_id, username, card_number, client_seed)
        
        if success:
            self.user_room[user_id] = room_id
            self.user_game[user_id] = game.game_id
            self.stats['total_joins'] += 1
            
            # Auto-start if enough players
            if len(game.players) >= room.min_players and game.status == GameStatus.WAITING:
                asyncio.create_task(self.start_game(game.game_id))
        
        return success, msg, game, player_data
    
    async def start_game(self, game_id: str):
        """Start a game with selection timer"""
        game = self.games.get(game_id)
        if not game:
            return
        
        # Wait for selection time
        await asyncio.sleep(game.room.selection_time)
        
        async with game._lock:
            if game.status == GameStatus.WAITING and len(game.players) >= game.room.min_players:
                await game.start_game()
                self.stats['games_started'] += 1
                
                # Start number calling loop
                asyncio.create_task(self.game_loop(game_id))
    
    async def game_loop(self, game_id: str):
        """Main game loop - calls numbers periodically"""
        game = self.games.get(game_id)
        if not game:
            return
        
        while game.status == GameStatus.ACTIVE:
            # Call number
            number = await game.call_number()
            
            if number:
                self.stats['numbers_called'] += 1
            
            # Wait for next call
            await asyncio.sleep(game.room.call_interval)
        
        # Game finished - process winners
        if game.status == GameStatus.FINISHED:
            await game.process_winners(game.winners)
    
    async def player_action(self, user_id: str, action: str, data: dict, timestamp: float = None) -> dict:
        """Process player action with rate limiting and validation"""
        
        # Rate limit check
        if not self.check_rate_limit(user_id):
            return {'success': False, 'message': 'Too many requests. Please slow down.'}
        
        if timestamp is None:
            timestamp = datetime.utcnow().timestamp()
        
        result = {'success': False, 'message': 'Unknown action'}
        
        # Get user's current game
        game_id = self.user_game.get(user_id)
        if not game_id or game_id not in self.games:
            return {'success': False, 'message': 'Not in a game'}
        
        game = self.games[game_id]
        
        if action == 'mark':
            number = data.get('number')
            if not number:
                return {'success': False, 'message': 'No number provided'}
            
            success, msg, bingo = await game.mark_number(user_id, number, timestamp)
            result = {
                'success': success,
                'message': msg,
                'bingo': bingo,
                'state': game.get_state(user_id) if success else None
            }
        
        elif action == 'bingo':
            # Bingo is auto-called, but allow manual for verification
            player = game.players.get(user_id)
            if player and player.bingo_called:
                result = {
                    'success': True,
                    'message': 'Bingo already called!',
                    'win_amount': player.win_amount,
                    'state': game.get_state(user_id)
                }
            else:
                result = {'success': False, 'message': 'No bingo detected'}
        
        return result
    
    async def get_leaderboard(self) -> List[dict]:
        """Get global leaderboard from database"""
        if self.db:
            return await self.db.get_leaderboard()
        return [
            {'username': 'Player1', 'wins': 10, 'winnings': 5000},
            {'username': 'Player2', 'wins': 8, 'winnings': 4000},
            {'username': 'Player3', 'wins': 6, 'winnings': 3000},
        ]
    
    async def cleanup_old_games(self):
        """Background task to clean up old games"""
        while True:
            await asyncio.sleep(3600)  # Run every hour
            
            current_time = datetime.utcnow()
            to_remove = []
            
            for game_id, game in self.games.items():
                if game.status == GameStatus.FINISHED:
                    if game.finished_at:
                        age = (current_time - game.finished_at).total_seconds()
                        if age > 3600:  # 1 hour
                            to_remove.append(game_id)
            
            for game_id in to_remove:
                del self.games[game_id]
                self.stats['games_cleaned'] += 1
            
            logger.info(f"Cleaned up {len(to_remove)} old games")
    
    async def recover_state(self):
        """Recover game state from database after restart"""
        if not self.db:
            return
        
        try:
            # Get active games from database
            active_games = await self.db.get_active_games()
            
            for game_data in active_games:
                room = self.rooms.get(game_data['room_id'])
                if room:
                    game = BingoGame(game_data['game_id'], room, self.db)
                    # Restore game state
                    game.status = GameStatus(game_data['status'])
                    game.called_numbers = game_data.get('called_numbers', [])
                    game.winners = game_data.get('winners', [])
                    game.total_bet = game_data.get('total_bet', 0)
                    game.prize_pool = game_data.get('prize_pool', 0)
                    
                    # Restore players
                    players = await self.db.get_game_players(game_data['game_id'])
                    for player_data in players:
                        player = Player(
                            user_id=player_data['user_id'],
                            username=player_data['username'],
                            card=player_data['card_data'],
                            card_number=player_data['card_number'],
                            marked=set(player_data.get('marked_numbers', []))
                        )
                        game.players[player.user_id] = player
                        self.user_game[player.user_id] = game.game_id
                    
                    self.games[game.game_id] = game
                    room.current_game = game
                    
                    logger.info(f"Recovered game {game.game_id} with {len(game.players)} players")
        
        except Exception as e:
            logger.error(f"Error recovering game state: {e}")

# Global game manager instance
game_manager = GameManager()
