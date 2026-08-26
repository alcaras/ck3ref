import data from '../data/entities.json';

export interface Entity {
  id: string;
  slug: string;
  type: string;
  name: string;
  page: string | null;
  icon?: string;
  scan?: boolean;
}

export const entities: Entity[] = (data as { entities: Entity[] }).entities;

const byId = new Map(entities.map((e) => [e.id, e]));

export function getEntity(id: string): Entity | undefined {
  return byId.get(id);
}
