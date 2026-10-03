"""Balance only the existing one-in-four geometry phase, preserving appearance.

With an even observation count, ``step % n`` and ``step % 4 == 3``
alias: some views can never update geometry. Give those geometry updates a
separate deterministic cursor; every appearance step retains its exact old
frame. Odd sizes already traverse all geometry views and stay unchanged.

This changes no observations, camera, phase, step count, or world/body
schedule. It does not promise one visit per combined epoch: preserving the
original appearance order is the controlled variable. The mapping is a
pure function of the saved absolute nextStep and ordered names.
"""


def scheduled_local_index(count, step):
    if isinstance(count,bool) or not isinstance(count,int) or count<1:
        raise ValueError('local_schedule_requires_positive_count')
    if isinstance(step,bool) or not isinstance(step,int) or step<0:
        raise ValueError('local_schedule_requires_nonnegative_step')
    if count%2==0 and step>=83 and step%4==3:
        return ((83%count)+(step-83)//4)%count
    return step%count


def scheduled_local_name(names, step):
    return names[scheduled_local_index(len(names),step)]


def schedule_receipt(names, steps, *, geometry_start=80, geometry_period=4, geometry_phase=3):
    """Record the actual two phase allocations without touching a model."""
    if len(set(names))!=len(names):raise ValueError('local_schedule_duplicate_observation')
    if (geometry_start,geometry_period,geometry_phase)!=(80,4,3):
        raise ValueError('local_schedule_receipt_requires_actual_one_in_four_phase')
    old={name:{'appearance':0,'geometry':0} for name in names}
    new={name:{'appearance':0,'geometry':0} for name in names}
    for step in range(steps):
        phase='geometry' if step>=geometry_start and step%geometry_period==geometry_phase else 'appearance'
        old[names[step%len(names)]][phase]+=1
        new[scheduled_local_name(names,step)][phase]+=1
    return {'method':'even_geometry_cursor_appearance_order_unchanged',
        'steps':steps,'geometryStart':geometry_start,'geometryPeriod':geometry_period,
        'geometryPhase':geometry_phase,'orderedNames':list(names),'before':old,'after':new,
        'oldMissingGeometry':[name for name in names if not old[name]['geometry']],
        'newMissingGeometry':[name for name in names if not new[name]['geometry']],
        'resumeState':'ordered names plus absolute nextStep; no hidden RNG or cursor',
        'appearanceFrameOrderExactlyUnchanged':True,
        'perCompleteCombinedEpochEachObservationOnce':False}
