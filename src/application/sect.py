"""@module application/sect
@purpose Pure building-capacity composition and fresh trusted Inventory command context.
@depends application/persistent,application/inventory,systems/sect,systems/inventory,Core/Data
@usedBy tests/systems/test_buildings; no HTTP or construction execution
@see ./INDEX.md
"""
from dataclasses import replace

from src.application.persistent import PersistentApplication
from src.application.inventory import commands
from src.core.state.envelope import StateEnvelope
from src.data.items.resources import BASE_CAPACITY, CAPACITY_PER_WAREHOUSE_LEVEL, warehouse_capacity
from src.systems.inventory import holdings
from src.systems.sect import buildings


def references(snapshot):
    return holdings.references(snapshot)+buildings.references(snapshot)


def validators(registry):
    return {'inventory':lambda p:holdings.validate(p,registry),'sect':lambda p:buildings.validate(p,registry)}


def new_state(registry, *, last_settled_at_ms):
    state=StateEnvelope.create(content_version=registry.content_version,
             data_schema_version=registry.schema_version,last_settled_at_ms=last_settled_at_ms,
             domains={'inventory':holdings.initial(),'sect':{'buildings':{}}})
    partition=buildings.initial(state.save_id,state.generation)
    return replace(state,domains={'inventory':holdings.initial(),'sect':partition},
                   identity={**state.identity,'instance_counter':len(partition['buildings'])})


def capacity_source(snapshot, registry):
    """Read-only diagnostic projection; neither Domain imports the other."""
    capability=buildings.capability(snapshot.domains['sect'],registry)
    levels=capability['warehouse_levels'];effective=warehouse_capacity(levels)
    used=holdings.stock_size(snapshot.domains['inventory'],registry)
    return {'base':BASE_CAPACITY,'warehouse_levels':levels,
            'warehouse_contribution':levels*CAPACITY_PER_WAREHOUSE_LEVEL,
            'effective':effective,'used':used,'over_capacity':max(0,used-effective)}


class SectApplication:
    """One SQLite Authority. Capacity is recomputed, never cached or saved.

    A changed Snapshot between projection and execute fails Foundation revision CAS.
    Replay remains Foundation-owned. No building setter or instant-upgrade command.
    """
    def __init__(self, store, registry):
        self.store,self.registry=store,registry
        self.foundation=PersistentApplication(store,registry,{},references=references,validators=validators(registry))

    def create(self,state):return self.foundation.create(state)
    def query(self,save_id):return self.foundation.query(save_id)
    def checkpoint(self,save_id):return self.foundation.checkpoint(save_id)
    def query_capacity(self,save_id):return capacity_source(self.query(save_id),self.registry)

    def execute(self,request):
        snapshot=self.query(request.save_id)
        capacity=capacity_source(snapshot,self.registry)['effective']
        application=PersistentApplication(self.store,self.registry,commands(self.registry,capacity=capacity),
                       references=references,validators=validators(self.registry))
        return application.execute(request)
