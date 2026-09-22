import { UserRepository } from '../infra/UserRepository';

/*
import { OrderRepository } from '../infra/OrderRepository';
*/

const snippet = `
import { CartRepository } from '../infra/CartRepository';
`;

export function handler() {
    return new UserRepository();
}
