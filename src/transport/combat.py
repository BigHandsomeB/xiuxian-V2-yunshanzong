"""Authenticated Combat query using the same game transport protection and errors."""
from flask import jsonify
from src.core.state.envelope import thaw_json

def register(app,application,save_id):
    @app.get('/api/combat')
    def combat_view():
        with application() as game:view=thaw_json(game.combat_view(save_id))
        return jsonify(protocol_version=1,combat=view)
