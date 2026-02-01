🎮 Strategy Survival Game (Python + Flask)

A logic-based multiplayer survival game inspired by Alice in Borderland.
This project focuses on strategy, probability, and elimination mechanics, built to practice real-world Python and backend concepts.

🧠 About the Game

The game simulates a high-pressure, decision-making environment where players compete across multiple rounds.

In each round:

Players submit a number within a time limit

The system calculates a target value using defined rules

Winners and losers are determined programmatically

Scores are updated dynamically

Players may be eliminated based on game conditions

This project was developed as a hands-on learning exercise to strengthen Python logic, backend flow, and game-state management.

🚀 Core Features

🎯 Strategy-based number selection

⏱️ Timed rounds with countdown logic

🧮 Rule-based winner calculation

❌ Automatic elimination system

🏆 Dynamic leaderboard & scoring

🔄 Round-based game state handling

🔊 Optional voice announcements (if enabled)

🛠️ Tech Stack

Language: Python

Backend Framework: Flask

Frontend: HTML, CSS, JavaScript

Database: SQLite

Tools: Git, GitHub, VS Code

ALICE-IN-BORDERLAND-GAME/
│
├── app.py                # Main Flask application
├── templates/
│   ├── index.html        # Game lobby / host screen
│   ├── form.html         # Player input interface
│   └── result.html       # Round results & leaderboard
│
├── static/               # CSS, JS, assets
├── database/
│   └── players.db        # SQLite database
│
├── requirements.txt
└── README.md
