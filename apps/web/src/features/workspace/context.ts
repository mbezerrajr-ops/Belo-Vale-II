import { createContext, useContext } from "react";
import type { Farm } from "../../api/types";
export const FarmContext = createContext<Farm | null>(null);
export const useActiveFarm = (): Farm | null => useContext(FarmContext);
