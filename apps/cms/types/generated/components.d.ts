import type { Schema, Struct } from '@strapi/strapi';

export interface SharedImageLayout extends Struct.ComponentSchema {
  collectionName: 'components_shared_image_layouts';
  info: {
    description: '\u041F\u043E\u043B\u043E\u0436\u0435\u043D\u0438\u0435 \u043E\u0442\u043D\u043E\u0441\u0438\u0442\u0435\u043B\u044C\u043D\u043E \u0442\u0435\u043A\u0441\u0442\u0430, \u043C\u0430\u043A\u0441\u0438\u043C\u0430\u043B\u044C\u043D\u044B\u0439 \u0440\u0430\u0437\u043C\u0435\u0440 \u0438 \u043F\u043E\u0434\u043F\u0438\u0441\u044C. \u0412 \u0443\u0437\u043A\u0438\u0445 \u0431\u043B\u043E\u043A\u0430\u0445 \u0438\u0437\u043E\u0431\u0440\u0430\u0436\u0435\u043D\u0438\u0435 \u0440\u0430\u0441\u043F\u043E\u043B\u0430\u0433\u0430\u0435\u0442\u0441\u044F \u0441\u0432\u0435\u0440\u0445\u0443.';
    displayName: '\u041E\u0444\u043E\u0440\u043C\u043B\u0435\u043D\u0438\u0435 \u0438\u0437\u043E\u0431\u0440\u0430\u0436\u0435\u043D\u0438\u044F';
  };
  attributes: {
    alignment: Schema.Attribute.Enumeration<['left', 'center', 'right']> &
      Schema.Attribute.Required &
      Schema.Attribute.DefaultTo<'center'>;
    caption: Schema.Attribute.Text;
    position: Schema.Attribute.Enumeration<['top', 'left', 'right']> &
      Schema.Attribute.Required &
      Schema.Attribute.DefaultTo<'top'>;
    size: Schema.Attribute.Enumeration<['small', 'medium', 'large', 'full']> &
      Schema.Attribute.Required &
      Schema.Attribute.DefaultTo<'medium'>;
  };
}

export interface SharedSection extends Struct.ComponentSchema {
  collectionName: 'components_shared_sections';
  info: {
    displayName: '\u0420\u0430\u0437\u0434\u0435\u043B';
  };
  attributes: {
    general: Schema.Attribute.Blocks;
    heading: Schema.Attribute.String;
    image: Schema.Attribute.Media<'images'>;
    imageLayout: Schema.Attribute.Component<'shared.image-layout', false>;
  };
}

export interface SharedSeo extends Struct.ComponentSchema {
  collectionName: 'components_shared_seos';
  info: {
    displayName: 'SEO';
  };
  attributes: {
    description: Schema.Attribute.Text;
    noindex: Schema.Attribute.Boolean & Schema.Attribute.DefaultTo<false>;
    title: Schema.Attribute.String;
  };
}

declare module '@strapi/strapi' {
  export namespace Public {
    export interface ComponentSchemas {
      'shared.image-layout': SharedImageLayout;
      'shared.section': SharedSection;
      'shared.seo': SharedSeo;
    }
  }
}
