"""Full-state export and independent cloud backup, without gameplay mutations."""
from src.core.save.backup import validate_save
from src.core.validation import ValidationError


class SaveBackup:
    def __init__(self, application, store, save_id):
        self.application, self.store, self.save_id = application, store, save_id

    def read(self):
        with self.application() as game:
            state = game.query(self.save_id).to_dict()
        return {'save': self.store.read(self.save_id), 'serverState': state}

    def put(self, body):
        if type(body) is not dict or set(body) != {'save', 'baseVersion'}:
            raise ValidationError('invalid backup request')
        state = validate_save(body['save'], self.save_id)
        with self.application() as game:
            current = game.query(self.save_id)
            if (state.content_version, state.data_schema_version) != (current.content_version, current.data_schema_version):
                raise ValidationError('backup content version mismatch')
            game.foundation.validate_state(state)
        return self.store.put(self.save_id, body['save'], body['baseVersion'])
