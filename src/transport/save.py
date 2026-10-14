"""Authenticated save transport; Application owns validation and persistence."""
from flask import jsonify, request
from src.core.save.backup import BackupConflict


def register(app, backups):
    app.config['GAME_SAVE_BACKUP_ENABLED'] = True

    @app.route('/api/save', methods=['GET', 'PUT'])
    def save_backup():
        if request.method == 'GET':
            return jsonify(backups.read())
        try:
            return jsonify(save=backups.put(request.get_json()))
        except BackupConflict as conflict:
            return jsonify(error='云端存档已变化，请读取并选择保留的存档。', code='SAVE_CONFLICT',
                           currentVersion=conflict.current_version), 409
