import type { Schema, Struct } from '@strapi/strapi';

export interface SharedSection extends Struct.ComponentSchema {
  collectionName: 'components_shared_sections';
  info: {
    displayName: '\u0420\u0430\u0437\u0434\u0435\u043B';
  };
  attributes: {
    heading: Schema.Attribute.String;
    text: Schema.Attribute.Text & Schema.Attribute.Required;
  };
}

export interface SharedSeo extends Struct.ComponentSchema {
  collectionName: 'components_shared_seos';
  info: {
    displayName: 'SEO';
  };
  attributes: {
    description: Schema.Attribute.Text;
    title: Schema.Attribute.String;
  };
}

declare module '@strapi/strapi' {
  export namespace Public {
    export interface ComponentSchemas {
      'shared.section': SharedSection;
      'shared.seo': SharedSeo;
    }
  }
}
